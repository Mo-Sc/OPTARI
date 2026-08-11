from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import patato as pat
from napari.utils import progress
from patato.io.attribute_tags import ReconAttributeTags
from qtpy.QtCore import Qt
from patari.controllers.base import TaskControllerBase
from patari.patato_bridge import display_data_from_patato_obj
from patari.utils.presets import PresetStore
from patari.utils.misc import download_file
from patari.utils.setup import get_user_reconstruction_presets_dir
from patari.utils.viewer import viewer_busy
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


def _resolve_deepmb_model(settings_dict: dict) -> dict:
    params = dict(settings_dict[ReconAttributeTags.ADDITIONAL_PARAMETERS])
    model_path = Path(params.pop("model_path")).expanduser()

    if not model_path.is_file():
        download_file(params["model_url"], model_path)

    params["model_path"] = str(model_path)
    params.pop("model_url", None)
    settings_dict[ReconAttributeTags.ADDITIONAL_PARAMETERS] = params
    return settings_dict


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
        try:
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
        except Exception as e:
            logger.exception("Error unbinding reconstruction dock signals: %s", e)

    def initialize_ui(self) -> None:
        """Populate the preset combo once."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction

        populate_preset_combo(dock.preset_combo, self.preset_store)

        self.on_preset_changed()
        self.refresh_ui()

    def refresh_ui(self) -> None:
        """Refresh scan-dependent controls. Reconstruction runs off the loaded scan, not a layer."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction
        pa_data = self.patari_controller.pa_data

        if pa_data is None:
            dock.scan_status_label.setText("No scan loaded")
            dock.run_button.setEnabled(False)
            return

        dock.scan_status_label.setText(Path(self.patari_controller.path).name)
        dock.run_button.setEnabled(True)

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
        """Run the selected reconstruction preset on the loaded scan and publish an output layer."""
        if self.patari_controller.reconstruction is None:
            return

        dock = self.patari_controller.reconstruction
        pa_data = self.patari_controller.pa_data

        if pa_data is None:
            dock.status_label.setText("Load a scan first.")
            return

        preset_path = dock.preset_combo.currentData()
        if preset_path is None:
            dock.status_label.setText("Select a reconstruction preset.")
            return

        if self._settings_dirty:
            dock.status_label.setText("Apply preset before running.")
            return

        settings_dict = dict(self._applied_settings)
        if settings_dict.get(ReconAttributeTags.RECONSTRUCTION_ALGORITHM) == (
            "DeepMB ONNX Reconstruction"
        ):
            settings_dict = _resolve_deepmb_model(settings_dict)

        offset_x_mm = float(settings_dict.pop("OFFSET_X", 0.0))
        offset_z_mm = float(settings_dict.pop("OFFSET_Z", 0.0))

        algorithm_name = settings_dict.get(
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

        dock.status_label.setText("Running reconstruction…")
        logger.info(
            "running reconstruction preset '%s' on %s frame(s), speed of sound=%s m/s",
            algorithm_name,
            len(output_frames),
            speed_of_sound,
        )

        # preprocessing -> reconstruction chain; run explicitly (not via run_pipeline) so the
        # UI-controlled speed of sound always overrides the preset/scan value on the final step.
        with viewer_busy(self.viewer):
            # Reconstruction has two sequential processing stages.
            with progress(total=2, desc="Reconstructing") as progress_bar:
                preprocessor = pat.read_reconstruction_preset(settings_dict)
                reconstruction_algorithm = preprocessor.children[0]
                time_series = pa_data_for_run.get_time_series()
                filtered_time_series, new_settings, _ = preprocessor.run(
                    time_series, pa_data_for_run
                )
                progress_bar.update(1)

                reconstruction, _, _ = reconstruction_algorithm.run(
                    filtered_time_series,
                    pa_data_for_run,
                    speed_of_sound=speed_of_sound,
                    **new_settings,
                )
                progress_bar.update(1)

        suffix_part = f"_{suffix}" if suffix else ""
        frame_part = f"_F{current_frame_id}" if current_frame_id is not None else ""
        layer_name = f"Recon: {algorithm_name}{suffix_part}{frame_part}"

        wavelengths = [int(w) for w in reconstruction.ax_1_labels]
        layer_metadata = {
            "type": "pa",
            "pa_kind": "recon",
            "wavelengths": wavelengths,
            "axis1_name": "Channel",
            "axis1_labels": wavelengths,
            "filepath": str(self.patari_controller.path),
            "timestamps": self.patari_controller.timestamps,
            "frames": output_frames,
        }

        data = self._expand_to_source_frames(
            display_data_from_patato_obj(reconstruction),
            output_frames,
            source_frame_count,
        )
        self._add_or_update_image_layer(
            layer_name,
            data,
            layer_metadata,
            reconstruction,
            colormap="viridis",
            units="mm",
            offset_x_mm=offset_x_mm,
            offset_z_mm=offset_z_mm,
        )
        self.patari_controller._patato_objects[layer_name] = reconstruction
        self.patari_controller._derived_patato_objects[layer_name] = reconstruction
        self.patari_controller._ensure_shapes_layer_on_top()

        dock.status_label.setText(f"Finished: {layer_name}")
        logger.info("reconstruction complete: %s", layer_name)
