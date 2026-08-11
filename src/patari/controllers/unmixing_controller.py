from __future__ import annotations

import logging

import numpy as np
import patato as pat
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QListWidgetItem

from patato.io.attribute_tags import UnmixingAttributeTags
from patato.unmixing.spectra import SPECTRA_NAMES
from patari.controllers.base import TaskControllerBase
from patari.patato_bridge import display_data_from_patato_obj
from patari.utils.presets import PresetStore
from patari.utils.setup import get_user_unmixing_presets_dir
from patari.widgets.dock_helpers import (
    add_preset_to_combo,
    populate_preset_combo,
    prompt_preset_name,
    remove_selected_preset,
)


logger = logging.getLogger(__name__)


class UnmixingController(TaskControllerBase):
    """Run spectral unmixing and add as layers."""

    def __init__(self, parent_controller):
        super().__init__(parent_controller)
        self.preset_store = PresetStore(get_user_unmixing_presets_dir())

    def bind_events(self) -> None:
        """Connect unmixing dock signals."""
        self.patari_controller.unmixing.preset_combo.currentIndexChanged.connect(
            self.on_preset_changed
        )
        self.patari_controller.unmixing.chromophores_list.itemChanged.connect(
            self.on_chromophores_changed
        )
        self.patari_controller.unmixing.select_all_wavelengths_button.clicked.connect(
            self.on_select_all_wavelengths_clicked
        )
        self.patari_controller.unmixing.clear_wavelengths_button.clicked.connect(
            self.on_clear_wavelengths_clicked
        )
        self.patari_controller.unmixing.run_button.clicked.connect(
            self.on_run_unmixing_clicked
        )
        self.patari_controller.unmixing.save_preset_button.clicked.connect(
            self.on_save_preset_clicked
        )
        self.patari_controller.unmixing.remove_preset_button.clicked.connect(
            self.on_remove_preset_clicked
        )

    def unbind_events(self) -> None:
        """Disconnect unmixing dock signals."""
        try:
            self.patari_controller.unmixing.preset_combo.currentIndexChanged.disconnect(
                self.on_preset_changed
            )
            self.patari_controller.unmixing.chromophores_list.itemChanged.disconnect(
                self.on_chromophores_changed
            )
            self.patari_controller.unmixing.select_all_wavelengths_button.clicked.disconnect(
                self.on_select_all_wavelengths_clicked
            )
            self.patari_controller.unmixing.clear_wavelengths_button.clicked.disconnect(
                self.on_clear_wavelengths_clicked
            )
            self.patari_controller.unmixing.run_button.clicked.disconnect(
                self.on_run_unmixing_clicked
            )
            self.patari_controller.unmixing.save_preset_button.clicked.disconnect(
                self.on_save_preset_clicked
            )
            self.patari_controller.unmixing.remove_preset_button.clicked.disconnect(
                self.on_remove_preset_clicked
            )
        except Exception as e:
            logger.exception("Error unbinding unmixing dock signals: %s", e)

    @staticmethod
    def _set_checked_by_text(list_widget, selected: set[str]) -> None:
        """Apply checked state to list items that match selected texts."""
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            state = Qt.Checked if item.text() in selected else Qt.Unchecked
            item.setCheckState(state)

    @staticmethod
    def _set_checked_wavelengths(list_widget, selected: set[int]) -> None:
        """Apply checked state to wavelength items in selected set."""
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            wavelength = int(item.data(Qt.UserRole))
            state = Qt.Checked if wavelength in selected else Qt.Unchecked
            item.setCheckState(state)

    def initialize_ui(self) -> None:
        """Initialize preset, chromophore, and wavelength controls once."""
        if self.patari_controller.unmixing is None:
            return

        dock = self.patari_controller.unmixing

        populate_preset_combo(dock.preset_combo, self.preset_store)

        if dock.chromophores_list.count() == 0:
            for name in sorted(SPECTRA_NAMES.keys()):
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                dock.chromophores_list.addItem(item)

        self.refresh_ui()
        self.on_chromophores_changed()

    def on_save_preset_clicked(self) -> None:
        """Save the current unmixing controls as a new user preset."""
        if self.patari_controller.unmixing is None:
            return

        dock = self.patari_controller.unmixing
        selected_wavelengths = [
            int(dock.wavelengths_list.item(i).data(Qt.UserRole))
            for i in range(dock.wavelengths_list.count())
            if dock.wavelengths_list.item(i).checkState() == Qt.Checked
        ]
        selected_chromophores = [
            dock.chromophores_list.item(i).text()
            for i in range(dock.chromophores_list.count())
            if dock.chromophores_list.item(i).checkState() == Qt.Checked
        ]
        preset_settings = {
            UnmixingAttributeTags.RESOLUTION_REDUCE: dock.resolution_reduction_factor.value(),
            UnmixingAttributeTags.UNMIXING_WAVELENGTHS: selected_wavelengths,
            UnmixingAttributeTags.SPECTRA: selected_chromophores,
            UnmixingAttributeTags.COMPUTE_THB: dock.generate_thb_checkbox.isChecked(),
            UnmixingAttributeTags.COMPUTE_SO2: dock.generate_so2_checkbox.isChecked(),
            UnmixingAttributeTags.SUFFIX: dock.suffix_edit.text().strip(),
        }
        preset_name = prompt_preset_name(
            dock.widget, dock.preset_combo, "unmixing_preset"
        )
        if preset_name is None:
            return

        try:
            preset_path = self.preset_store.save(preset_name, preset_settings)
        except (ValueError, OSError) as exc:
            dock.status_label.setText(f"Could not save preset: {exc}")
            return

        add_preset_to_combo(dock.preset_combo, preset_path)
        dock.status_label.setText(f"Saved preset: {preset_path.name}")
        self.on_preset_changed()

    def on_remove_preset_clicked(self) -> None:
        if self.patari_controller.unmixing is None:
            return

        dock = self.patari_controller.unmixing
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

    def refresh_ui(self) -> None:
        """Refresh source-dependent controls from the active layer."""
        if self.patari_controller.unmixing is None:
            return

        dock = self.patari_controller.unmixing
        active_recon_layer = self.patari_controller.active_recon_layer

        if active_recon_layer is None or active_recon_layer.metadata["pa_kind"] != "recon":
            dock.source_layer_label.setText("Select a PA reconstruction layer")
            dock.wavelengths_list.clear()
            # disable unmixing button when no valid source is active
            dock.run_button.setEnabled(False)
            return

        dock.source_layer_label.setText(active_recon_layer.name)

        # Enable unmixing button
        dock.run_button.setEnabled(True)

        wavelengths = active_recon_layer.metadata.get("wavelengths") or []
        source_name = active_recon_layer.name
        last_source = dock.widget.property("_unmixing_source_name")

        # Keep manual wavelength selections while the same source stays active.
        if last_source == source_name and dock.wavelengths_list.count() > 0:
            return

        dock.widget.setProperty("_unmixing_source_name", source_name)
        dock.wavelengths_list.clear()
        for w in wavelengths:
            wavelength = int(w)
            item = QListWidgetItem(f"{wavelength} nm")
            item.setData(Qt.UserRole, wavelength)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            dock.wavelengths_list.addItem(item)

        self.on_preset_changed()

    def on_select_all_wavelengths_clicked(self) -> None:
        """Select all source wavelengths in the list widget."""
        if self.patari_controller.unmixing is None:
            return
        for i in range(
            self.patari_controller.unmixing.wavelengths_list.count()
        ):
            self.patari_controller.unmixing.wavelengths_list.item(
                i
            ).setCheckState(Qt.Checked)

    def on_clear_wavelengths_clicked(self) -> None:
        """Clear all source wavelength selections in the list widget."""
        if self.patari_controller.unmixing is None:
            return
        for i in range(
            self.patari_controller.unmixing.wavelengths_list.count()
        ):
            self.patari_controller.unmixing.wavelengths_list.item(
                i
            ).setCheckState(Qt.Unchecked)

    def on_preset_changed(self) -> None:
        """Load selected preset values into the unmixing controls."""
        if self.patari_controller.unmixing is None:
            return

        dock = self.patari_controller.unmixing
        preset_path = dock.preset_combo.currentData()
        if preset_path is None:
            return

        try:
            settings = self.preset_store.load(preset_path)
            reduce_factor = int(
                settings.get(UnmixingAttributeTags.RESOLUTION_REDUCE, 1)
            )
            spectra = set(settings.get(UnmixingAttributeTags.SPECTRA, []))
            selected_wavelengths = set()
            wavelength_range = settings.get(UnmixingAttributeTags.WAVELENGTH_RANGE)
            if wavelength_range is not None and len(wavelength_range) == 2:
                start, end = int(wavelength_range[0]), int(wavelength_range[1])
                selected_wavelengths = {
                    int(dock.wavelengths_list.item(i).data(Qt.UserRole))
                    for i in range(dock.wavelengths_list.count())
                    if start
                    <= int(dock.wavelengths_list.item(i).data(Qt.UserRole))
                    <= end
                }

            explicit_wavelengths = settings.get(
                UnmixingAttributeTags.UNMIXING_WAVELENGTHS
            )
            if explicit_wavelengths is not None:
                selected_wavelengths = {int(w) for w in explicit_wavelengths}

            compute_so2 = settings.get(UnmixingAttributeTags.COMPUTE_SO2, True)
            compute_thb = settings.get(UnmixingAttributeTags.COMPUTE_THB, True)
            suffix = str(settings.get(UnmixingAttributeTags.SUFFIX, ""))
        except (TypeError, ValueError, KeyError, OSError) as exc:
            dock.status_label.setText(f"Could not apply preset: {exc}")
            return

        dock.resolution_reduction_factor.setValue(max(1, reduce_factor))
        dock.suffix_edit.setText(suffix)
        self._set_checked_by_text(dock.chromophores_list, spectra)
        self._set_checked_wavelengths(dock.wavelengths_list, selected_wavelengths)
        dock.generate_so2_checkbox.setChecked(bool(compute_so2))
        dock.generate_thb_checkbox.setChecked(bool(compute_thb))
        self.on_chromophores_changed()

    def on_chromophores_changed(self) -> None:
        """
        Enable THb and sO2 options only when Hb and HbO2 are selected.
        so2 is activated by default 
        """
        if self.patari_controller.unmixing is None:
            return

        dock = self.patari_controller.unmixing
        selected = {
            dock.chromophores_list.item(i).text()
            for i in range(dock.chromophores_list.count())
            if dock.chromophores_list.item(i).checkState() == Qt.Checked
        }
        hb_pair_available = "Hb" in selected and "HbO2" in selected

        dock.generate_so2_checkbox.setEnabled(hb_pair_available)
        dock.generate_thb_checkbox.setEnabled(hb_pair_available)
        if not hb_pair_available:
            dock.generate_so2_checkbox.setChecked(False)
            dock.generate_thb_checkbox.setChecked(False)

    @staticmethod
    def _set_export_frame_attrs(
        image_sequence,
        export_attrs: dict,
    ) -> None:
        """Apply export attributes to PATATO output objects."""
        for key, value in export_attrs.items():
            image_sequence.attributes[key] = value

    @staticmethod
    def _build_output_metadata(
        *,
        source_layer_name: str,
        output_frames: list[int],
        axis1_labels: list[str],
        filepath,
        timestamps,
        pa_kind: str,
        frame_mode: str,
        parameter: str | None = None,
        include_chromophores: bool = False,
        settings: dict,
    ) -> tuple[dict, dict]:
        """Build synchronized layer metadata and HDF5 export attributes."""
        layer_metadata = {
            "type": "pa",
            "pa_kind": pa_kind,
            "source_layer": source_layer_name,
            "frames": output_frames,
            "axis1_name": "Channel",
            "axis1_labels": axis1_labels,
            "filepath": filepath,
            "timestamps": timestamps,
        }
        if include_chromophores:
            layer_metadata["chromophores"] = axis1_labels
        if parameter is not None:
            layer_metadata["parameter"] = parameter
        layer_metadata["settings"] = settings

        export_attrs = {
            "frames": np.asarray(output_frames, dtype=int),
            "source_layer": str(source_layer_name),
            "axis1_labels": np.asarray(axis1_labels, dtype=str),
            "pa_kind": str(pa_kind),
            "source_frame_mode": str(frame_mode),
        }
        if parameter is not None:
            export_attrs["parameter"] = str(parameter)

        return layer_metadata, export_attrs

    def on_run_unmixing_clicked(self) -> None:
        """Execute unmixing for the selected setup and publish output layers."""
        if self.patari_controller.unmixing is None:
            return

        dock = self.patari_controller.unmixing

        if self.patari_controller.active_recon_layer is None:
            dock.status_label.setText("Select a PA reconstruction layer.")
            return

        recon = self.patari_controller._patato_objects.get(
            self.patari_controller.active_recon_layer.name
        )
        if recon is None:
            dock.status_label.setText("Source layer must be a reconstruction.")
            return

        selected_wavelengths = [
            int(dock.wavelengths_list.item(i).data(Qt.UserRole))
            for i in range(dock.wavelengths_list.count())
            if dock.wavelengths_list.item(i).checkState() == Qt.Checked
        ]
        selected_chromophores = [
            dock.chromophores_list.item(i).text()
            for i in range(dock.chromophores_list.count())
            if dock.chromophores_list.item(i).checkState() == Qt.Checked
        ]

        if not selected_wavelengths:
            dock.status_label.setText("Select at least one wavelength.")
            return
        if not selected_chromophores:
            dock.status_label.setText("Select at least one chromophore.")
            return

        frame_numbers = list(
            self.patari_controller.active_recon_layer.metadata.get("frames")
            or range(recon.shape[0])
        )
        # Run against all reconstructed frames by default.
        recon_for_run = recon
        output_frames = frame_numbers
        current_frame_id = None
        frame_mode = "all"

        if dock.current_frames_radio.isChecked():
            current_frame = int(self.viewer.dims.current_step[0])
            if current_frame not in frame_numbers:
                dock.status_label.setText(
                    "Selected frame is not reconstructed."
                )
                return
            recon_idx = frame_numbers.index(current_frame)
            # PATATO expects a contiguous slice, then we remap to acquisition frame ids.
            recon_for_run = recon[recon_idx : recon_idx + 1]
            output_frames = [current_frame]
            current_frame_id = current_frame
            frame_mode = "current"

        suffix = dock.suffix_edit.text().strip()
        reduce_factor = int(dock.resolution_reduction_factor.value())
        settings = {
            "wavelengths": selected_wavelengths,
            "chromophores": selected_chromophores,
            "resolution_reduction_factor": reduce_factor,
            "suffix": suffix,
            "frame_mode": frame_mode,
            "frames": output_frames,
            "generate_thb": dock.generate_thb_checkbox.isChecked(),
            "generate_so2": dock.generate_so2_checkbox.isChecked(),
        }

        dock.status_label.setText("Running unmixing…")

        logger.info(
            "running unmixing for %s with %s wavelength(s), %s chromophore(s), reduce=%s",
            self.patari_controller.active_recon_layer.name,
            len(selected_wavelengths),
            len(selected_chromophores),
            reduce_factor,
        )

        unmixer = pat.SpectralUnmixer(
            chromophores=selected_chromophores,
            wavelengths=np.array(selected_wavelengths, dtype=float),
            rescaling_factor=reduce_factor,
            algorithm_id=suffix,
        )
        unmixed, _, _ = unmixer.run(
            recon_for_run, self.patari_controller.pa_data
        )
        unmixed_axis1_labels = list(map(str, unmixed.ax_1_labels))
        unmixed_metadata, unmixed_export_attrs = self._build_output_metadata(
            source_layer_name=self.patari_controller.active_recon_layer.name,
            output_frames=output_frames,
            axis1_labels=unmixed_axis1_labels,
            filepath=self.patari_controller.active_recon_layer.metadata.get(
                "filepath"
            ),
            timestamps=self.patari_controller.active_recon_layer.metadata.get(
                "timestamps"
            ),
            pa_kind="unmixed",
            frame_mode=frame_mode,
            include_chromophores=True,
            settings=settings,
        )
        self._set_export_frame_attrs(unmixed, unmixed_export_attrs)

        source_name = self.patari_controller.active_recon_layer.name.replace(
            "Recon: ", ""
        )
        suffix_part = f"_{suffix}" if suffix else ""
        # Encode the acquisition-frame index when only a single frame is unmixed.
        frame_part = (
            f"_F{current_frame_id}" if current_frame_id is not None else ""
        )

        unmixed_name = f"Unmixed: {source_name}{suffix_part}{frame_part}"
        source_frame_count = int(
                np.asarray(self.patari_controller.active_recon_layer.data).shape[0]
        )
        unmixed_data = self._expand_to_source_frames(
            display_data_from_patato_obj(unmixed),
            output_frames,
            source_frame_count,
        )
        # Channel labels are used by downstream spectrum displays.
        self._add_or_update_image_layer(
            name=unmixed_name,
            data=unmixed_data,
            metadata=unmixed_metadata,
            patato_obj=unmixed,
            colormap="magma",
        )
        # Keep PATATO outputs available for future derived computations.
        self.patari_controller._derived_patato_objects[unmixed_name] = unmixed

        generated = ["unmixed"]

        if dock.generate_thb_checkbox.isChecked():
            thb_calc = pat.THbCalculator(algorithm_id=suffix)
            thb, _, _ = thb_calc.run(unmixed, self.patari_controller.pa_data)
            thb_metadata, thb_export_attrs = self._build_output_metadata(
                source_layer_name=self.patari_controller.active_recon_layer.name,
                output_frames=output_frames,
                axis1_labels=["thb"],
                filepath=self.patari_controller.active_recon_layer.metadata.get(
                    "filepath"
                ),
                timestamps=self.patari_controller.active_recon_layer.metadata.get(
                    "timestamps"
                ),
                pa_kind="unmixed_param",
                frame_mode=frame_mode,
                parameter="thb",
                settings=settings,
            )
            self._set_export_frame_attrs(thb, thb_export_attrs)
            thb_name = f"THb: {source_name}{suffix_part}{frame_part}"
            self._add_or_update_image_layer(
                name=thb_name,
                data=self._expand_to_source_frames(
                    display_data_from_patato_obj(thb),
                    output_frames,
                    source_frame_count,
                ),
                metadata=thb_metadata,
                patato_obj=thb,
                colormap="inferno",
            )
            self.patari_controller._derived_patato_objects[thb_name] = thb
            generated.append("thb")

        if dock.generate_so2_checkbox.isChecked():
            so2_calc = pat.SO2Calculator(algorithm_id=suffix, nan_invalid=True)
            so2, _, _ = so2_calc.run(unmixed, self.patari_controller.pa_data)
            so2_metadata, so2_export_attrs = self._build_output_metadata(
                source_layer_name=self.patari_controller.active_recon_layer.name,
                output_frames=output_frames,
                axis1_labels=["so2"],
                filepath=self.patari_controller.active_recon_layer.metadata.get(
                    "filepath"
                ),
                timestamps=self.patari_controller.active_recon_layer.metadata.get(
                    "timestamps"
                ),
                pa_kind="unmixed_param",
                frame_mode=frame_mode,
                parameter="so2",
                settings=settings,
            )
            self._set_export_frame_attrs(so2, so2_export_attrs)
            so2_name = f"sO2: {source_name}{suffix_part}{frame_part}"
            self._add_or_update_image_layer(
                name=so2_name,
                data=self._expand_to_source_frames(
                    display_data_from_patato_obj(so2),
                    output_frames,
                    source_frame_count,
                ),
                metadata=so2_metadata,
                patato_obj=so2,
                colormap="twilight_shifted",
            )
            self.patari_controller._derived_patato_objects[so2_name] = so2
            generated.append("so2")

        # Reassert ROI visibility priority after adding multiple result layers.
        self.patari_controller._ensure_shapes_layer_on_top()

        dock.status_label.setText(f"Finished: {', '.join(generated)}")
        logger.info("unmixing complete: %s", ", ".join(generated))
