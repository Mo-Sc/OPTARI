from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from functools import partial
from math import ceil
from pathlib import Path

import patato as pat
from patato import PAT_MAXIMUM_BATCH_SIZE
from patato.io.attribute_tags import ReconAttributeTags
from qtpy.QtCore import Qt
from patari.controllers.base import TaskControllerBase
from patari.patato_bridge import display_data_from_patato_obj
from patari.utils.presets import PresetStore
from patari.utils.setup import get_user_reconstruction_presets_dir
from patari.utils.tasks import download_then, start_task
from patari.widgets.reconstruction_dock import (
    SPEED_OF_SOUND_DEFAULT,
    SPEED_OF_SOUND_MAX,
    SPEED_OF_SOUND_MIN,
)
from patari.widgets.dock_helpers import (
    add_preset_to_combo,
    populate_preset_combo,
    prompt_preset_name,
    remove_selected_preset,
)

logger = logging.getLogger(__name__)

DEEPMB_ALGORITHM = "DeepMB ONNX Reconstruction"


def _resolve_deepmb_model(settings_dict: dict, model_path: Path) -> None:
    """Rewrite the DeepMB params in place so PATATO sees a local path.

    `model_url` is patari-only and must be removed before the dict reaches PATATO. 
    """
    params = dict(settings_dict[ReconAttributeTags.ADDITIONAL_PARAMETERS])
    params["model_path"] = str(model_path)
    params.pop("model_url", None)
    settings_dict[ReconAttributeTags.ADDITIONAL_PARAMETERS] = params


def _reconstruct_frames(
    settings: dict, pa_data, speed_of_sound: float, chunk_frames: int
) -> Iterator[None]:
    """Preprocess and reconstruct *pa_data* in frame chunks, yielding once per finished chunk.

    Runs in a worker thread, so it must not touch Qt or napari. The preprocessing ->
    reconstruction chain is run explicitly (not via patato's run_pipeline) so the
    UI-controlled speed of sound overrides the preset/scan value on the final step.
    """
    preprocessor = pat.read_reconstruction_preset(settings)
    reconstruction_algorithm = preprocessor.children[0]
    yield  # setup tick: building the algorithm loads the ONNX model for DeepMB

    chunks = []
    new_settings: dict = {}
    for start in range(0, int(pa_data.shape[0]), chunk_frames):
        frames = pa_data[start : start + chunk_frames]
        filtered_time_series, new_settings, _ = preprocessor.run(
            frames.get_time_series(), frames
        )
        reconstruction, _, _ = reconstruction_algorithm.run(
            filtered_time_series,
            frames,
            speed_of_sound=speed_of_sound,
            **new_settings,
        )
        chunks.append(reconstruction)
        yield

    return pat.ImageSequence.concat(chunks), new_settings


class ReconstructionController(TaskControllerBase):
    """Run PATATO reconstruction presets on the loaded scan and add as layers."""

    def __init__(self, parent_controller):
        super().__init__(parent_controller)
        self._updating_settings = False
        self._settings_dirty = False
        self._applied_settings: dict = {}
        self.preset_store = PresetStore(get_user_reconstruction_presets_dir())

    def bind_events(self) -> None:
        """Connect reconstruction dock signals."""
        dock = self.patari_controller.reconstruction
        dock.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        dock.all_settings_button.toggled.connect(self.on_all_settings_toggled)
        dock.settings_edit.textChanged.connect(self.on_settings_text_changed)
        dock.apply_preset_button.clicked.connect(self.on_apply_preset_clicked)
        dock.save_preset_button.clicked.connect(self.on_save_preset_clicked)
        dock.remove_preset_button.clicked.connect(self.on_remove_preset_clicked)
        dock.speed_of_sound_slider.valueChanged.connect(
            self.on_speed_of_sound_changed
        )
        dock.run_button.clicked.connect(self.on_run_reconstruction_clicked)

    def unbind_events(self) -> None:
        """Disconnect reconstruction dock signals."""
        dock = self.patari_controller.reconstruction
        dock.preset_combo.currentIndexChanged.disconnect(self.on_preset_changed)
        dock.all_settings_button.toggled.disconnect(self.on_all_settings_toggled)
        dock.settings_edit.textChanged.disconnect(self.on_settings_text_changed)
        dock.apply_preset_button.clicked.disconnect(self.on_apply_preset_clicked)
        dock.save_preset_button.clicked.disconnect(self.on_save_preset_clicked)
        dock.remove_preset_button.clicked.disconnect(self.on_remove_preset_clicked)
        dock.speed_of_sound_slider.valueChanged.disconnect(
            self.on_speed_of_sound_changed
        )
        dock.run_button.clicked.disconnect(self.on_run_reconstruction_clicked)

    def initialize_ui(self) -> None:
        """Populate the preset combo once."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction

        populate_preset_combo(dock.preset_combo, self.preset_store)

        self.on_preset_changed()
        self.refresh_ui()

    _NO_SCAN_MESSAGE = "No scan loaded."

    def refresh_ui(self) -> None:
        """Refresh scan-dependent controls. Reconstruction runs off the loaded scan, not a
        layer. There is no "Source" to pick, so the only thing to reflect here is whether a
        scan is loaded at all."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction
        pa_data = self.patari_controller.pa_data

        if pa_data is None:
            dock.status_label.setText(self._NO_SCAN_MESSAGE)
            dock.run_button.setEnabled(False)
            return

        if dock.status_label.text() == self._NO_SCAN_MESSAGE:
            dock.status_label.setText("Select a preset and run.")
        dock.run_button.setEnabled(not self.patari_controller.task_running)

    def on_preset_changed(self) -> None:
        """Load the selected preset into the in-memory settings editor."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction
        preset_path = dock.preset_combo.currentData()
        if preset_path is None:
            self._set_settings_editor({})
            return

        try:
            preset_settings = self.preset_store.load(preset_path)
            speed_of_sound = int(
                preset_settings.get(
                    ReconAttributeTags.SPEED_OF_SOUND, SPEED_OF_SOUND_DEFAULT
                )
            )
            self._set_settings_editor(preset_settings)
            self._applied_settings = preset_settings
            self._settings_dirty = False
            self._set_speed_of_sound_slider(speed_of_sound)
        except (ValueError, OSError) as e:
            dock.status_label.setText(f"Could not load preset: {e}")
            return

    def on_all_settings_toggled(self, checked: bool) -> None:
        """Show or hide the in-memory JSON settings editor."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction
        dock.settings_edit.setVisible(checked)
        dock.apply_preset_button.setVisible(checked)
        dock.all_settings_button.setArrowType(
            Qt.DownArrow if checked else Qt.RightArrow
        )

    def on_settings_text_changed(self) -> None:
        """Mark the editor contents as pending without rewriting the document."""
        if self._updating_settings:
            return
        self._settings_dirty = True

    def on_apply_preset_clicked(self) -> None:
        """Validate and apply the edited JSON settings in memory."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction
        try:
            settings_dict = json.loads(dock.settings_edit.toPlainText())
        except json.JSONDecodeError as exc:
            dock.status_label.setText(f"Invalid JSON settings: {exc.msg}")
            return
        if not isinstance(settings_dict, dict):
            dock.status_label.setText("JSON settings must be an object.")
            return

        self._applied_settings = settings_dict
        self._settings_dirty = False
        speed_of_sound = settings_dict.get(
            ReconAttributeTags.SPEED_OF_SOUND, SPEED_OF_SOUND_DEFAULT
        )
        self._set_speed_of_sound_slider(speed_of_sound)
        dock.status_label.setText("Preset applied.")

    def on_remove_preset_clicked(self) -> None:
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction
        preset_path = dock.preset_combo.currentData()
        if preset_path is None:
            dock.status_label.setText("Select a preset to remove.")
            return

        try:
            removed_path, removed = remove_selected_preset(
                dock.preset_combo, self.preset_store
            )
        except (ValueError, OSError) as exc:
            dock.status_label.setText(f"Could not remove preset: {exc}")
            return
        if not removed:
            dock.status_label.setText(f"Preset not found: {preset_path.name}")
            return

        dock.status_label.setText(f"Removed preset: {removed_path.name}")

    def on_save_preset_clicked(self) -> None:
        """Save the current JSON editor contents as a new user preset."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction
        try:
            settings_dict = json.loads(dock.settings_edit.toPlainText())
        except json.JSONDecodeError as exc:
            dock.status_label.setText(f"Invalid JSON settings: {exc.msg}")
            return
        if not isinstance(settings_dict, dict):
            dock.status_label.setText("JSON settings must be an object.")
            return

        preset_name = prompt_preset_name(
            dock.widget, dock.preset_combo, "reconstruction_preset"
        )
        if preset_name is None:
            return

        try:
            preset_path = self.preset_store.save(preset_name, settings_dict)
        except (ValueError, OSError) as exc:
            dock.status_label.setText(f"Could not save preset: {exc}")
            return

        add_preset_to_combo(dock.preset_combo, preset_path)
        dock.status_label.setText(f"Saved preset: {preset_path.name}")

    def _set_settings_editor(self, settings_dict: dict) -> None:
        dock = self.patari_controller.reconstruction
        self._updating_settings = True
        try:
            dock.settings_edit.setPlainText(json.dumps(settings_dict, indent=2))
        finally:
            self._updating_settings = False

    def _set_speed_of_sound_slider(self, speed_of_sound) -> None:
        dock = self.patari_controller.reconstruction
        clamped = max(SPEED_OF_SOUND_MIN, min(SPEED_OF_SOUND_MAX, int(speed_of_sound)))
        self._updating_settings = True
        try:
            dock.speed_of_sound_slider.setValue(clamped)
        finally:
            self._updating_settings = False
        self.on_speed_of_sound_changed(clamped)

    def on_speed_of_sound_changed(self, value: int) -> None:
        """Keep the speed of sound label in sync with the slider."""
        if self.patari_controller.reconstruction is None:
            return
        dock = self.patari_controller.reconstruction
        dock.speed_of_sound_value_label.setText(f"{value} m/s")

    def on_run_reconstruction_clicked(self) -> None:
        """Start the selected reconstruction preset on the loaded scan in a worker thread."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction
        pa_data = self.patari_controller.pa_data

        if pa_data is None:
            dock.status_label.setText("Load a scan first.")
            return

        if dock.preset_combo.currentData() is None:
            dock.status_label.setText("Select a reconstruction preset.")
            return

        if self._settings_dirty:
            dock.status_label.setText("Apply preset before running.")
            return

        settings = dict(self._applied_settings)
        offset_x_mm = float(settings.pop("OFFSET_X", 0.0))
        offset_z_mm = float(settings.pop("OFFSET_Z", 0.0))

        algorithm_name = settings.get(
            ReconAttributeTags.RECONSTRUCTION_ALGORITHM, "Reconstruction"
        )
        suffix = dock.suffix_edit.text().strip()
        speed_of_sound = float(dock.speed_of_sound_slider.value())

        source_frame_count = int(pa_data.shape[0])
        pa_data_for_run = pa_data
        output_frames = list(range(source_frame_count))
        current_frame_id = None

        if dock.current_frames_radio.isChecked():
            current_frame = int(self.viewer.dims.current_step[0])
            if not (0 <= current_frame < source_frame_count):
                dock.status_label.setText("Selected frame is not available.")
                return
            pa_data_for_run = pa_data[current_frame : current_frame + 1]
            output_frames = [current_frame]
            current_frame_id = current_frame

        n_wavelengths = max(1, int(pa_data.shape[1]))
        chunk_frames = max(1, PAT_MAXIMUM_BATCH_SIZE // n_wavelengths)
        n_chunks = ceil(len(output_frames) / chunk_frames)

        def publish(result) -> None:
            """Add the finished reconstruction as a layer. Runs on the main thread."""
            reconstruction, new_settings = result

            suffix_part = f"_{suffix}" if suffix else ""
            frame_part = f"_F{current_frame_id}" if current_frame_id is not None else ""
            layer_name = f"Recon: {algorithm_name}{suffix_part}{frame_part}"

            wavelengths = [int(w) for w in reconstruction.ax_1_labels]
            settings.update(new_settings)
            settings.update(
                {
                    ReconAttributeTags.RECONSTRUCTION_ALGORITHM: algorithm_name,
                    ReconAttributeTags.SPEED_OF_SOUND: speed_of_sound,
                    "OFFSET_X": offset_x_mm,
                    "OFFSET_Z": offset_z_mm,
                    "frame_mode": "current" if current_frame_id is not None else "all",
                    "frames": output_frames,
                    "suffix": suffix,
                }
            )
            layer_metadata = {
                "type": "pa",
                "pa_kind": "recon",
                "wavelengths": wavelengths,
                "axis1_name": "Channel",
                "axis1_labels": wavelengths,
                "filepath": str(self.patari_controller.path),
                "timestamps": self.patari_controller.timestamps,
                "frames": output_frames,
                "settings": settings,
            }

            data = self._expand_to_source_frames(
                display_data_from_patato_obj(reconstruction),
                output_frames,
                source_frame_count,
            )

            # absolute placement: a recon comes from the raw time series, so it must not
            # inherit (and re-apply) the offset of whichever layer is currently active
            translate = (0.0,) * (data.ndim - 2) + (offset_z_mm, offset_x_mm)

            self._add_or_update_image_layer(
                layer_name,
                data,
                layer_metadata,
                reconstruction,
                colormap="viridis",
                translate=translate,
            )
            self.patari_controller._patato_objects[layer_name] = reconstruction
            self.patari_controller._derived_patato_objects[layer_name] = reconstruction
            self.patari_controller._ensure_shapes_layer_on_top()

            dock.status_label.setText(f"Finished: {layer_name}")
            logger.info("reconstruction complete: %s", layer_name)

        def reconstruct() -> None:
            dock.status_label.setText(f"Reconstructing {len(output_frames)} frame(s)…")
            logger.info(
                "running reconstruction preset '%s' on %s frame(s) in %s chunk(s) of %s, "
                "speed of sound=%s m/s",
                algorithm_name,
                len(output_frames),
                n_chunks,
                chunk_frames,
                speed_of_sound,
            )
            start_task(
                self.patari_controller,
                partial(
                    _reconstruct_frames,
                    settings,
                    pa_data_for_run,
                    speed_of_sound,
                    chunk_frames,
                ),
                total=n_chunks + 1,
                desc="Reconstructing",
                on_result=publish,
                status_label=dock.status_label,
            )

        if algorithm_name != DEEPMB_ALGORITHM:
            reconstruct()
            return

        # DeepMB needs its ONNX weights on disk before the preset can be built.
        params = settings[ReconAttributeTags.ADDITIONAL_PARAMETERS]
        model_path = Path(params["model_path"]).expanduser()

        def resolve_and_reconstruct() -> None:
            _resolve_deepmb_model(settings, model_path)
            reconstruct()

        download_then(
            self.patari_controller,
            model_path,
            params.get("model_url"),
            dock.status_label,
            resolve_and_reconstruct,
        )
