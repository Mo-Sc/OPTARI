from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import patato as pat
import patato.unmixing as pat_unmixing
from napari.layers import Image
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QListWidgetItem

from patato.io.attribute_tags import UnmixingAttributeTags
from patato.unmixing.spectra import SPECTRA_NAMES
from patari.controllers.base import TaskControllerBase


logger = logging.getLogger(__name__)


class UnmixingController(TaskControllerBase):
    """Run spectral unmixing and add as layers."""

    def __init__(self, parent_controller):
        super().__init__(parent_controller)

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

        if dock.preset_combo.count() == 0:
            # fill with available presets from user directory
            from patari.utils.setup import get_user_unmixing_presets_dir
            preset_dir = get_user_unmixing_presets_dir()

            for preset_path in sorted(preset_dir.glob("*.json")):
                dock.preset_combo.addItem(
                    preset_path.stem, userData=preset_path
                )
            if dock.preset_combo.count() > 0:
                dock.preset_combo.setCurrentIndex(0)

        if dock.chromophores_list.count() == 0:
            for name in sorted(SPECTRA_NAMES.keys()):
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                dock.chromophores_list.addItem(item)

        self.refresh_ui()
        self.on_chromophores_changed()
        self.on_preset_changed()

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

        # load unmixing preset from user directory
        settings = json.loads(Path(preset_path).read_text())

        reduce_factor = int(
            settings.get(UnmixingAttributeTags.RESOLUTION_REDUCE, 1)
        )
        dock.resolution_reduction_factor.setValue(max(1, reduce_factor))
        dock.suffix_edit.setText(
            str(settings.get(UnmixingAttributeTags.SUFFIX, ""))
        )

        spectra = set(settings.get(UnmixingAttributeTags.SPECTRA, []))
        self._set_checked_by_text(dock.chromophores_list, spectra)

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

        explicit_wavelengths = settings.get(UnmixingAttributeTags.UNMIXING_WAVELENGTHS)
        if explicit_wavelengths is not None:
            explicit_set = {int(w) for w in explicit_wavelengths}
            selected_wavelengths = explicit_set

        if selected_wavelengths:
            self._set_checked_wavelengths(dock.wavelengths_list, selected_wavelengths)

        compute_so2 = settings.get(UnmixingAttributeTags.COMPUTE_SO2, True)
        dock.generate_so2_checkbox.setChecked(bool(compute_so2))

        compute_thb = settings.get(UnmixingAttributeTags.COMPUTE_THB, True)
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
        dock.generate_so2_checkbox.setChecked(hb_pair_available)

        if not hb_pair_available:
            dock.generate_so2_checkbox.setChecked(False)
            dock.generate_thb_checkbox.setChecked(False)

    @staticmethod
    def _extract_display_data(image_sequence) -> np.ndarray:
        """Convert PATATO sequence to viewer data orientation."""
        return np.flip(np.array(image_sequence.da[:, :, :, 0, :]), axis=-2)

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

    @staticmethod
    def _expand_to_source_frames(
        data: np.ndarray,
        output_frames: list[int],
        source_frame_count: int,
    ) -> np.ndarray:
        """Pad computed frames to source frame indexing when needed."""
        if data.shape[0] == source_frame_count:
            return data

        # Map computed frames into the acquisition frame index space.
        # This preserves frame-aligned indexing with sparse reconstructions.
        expanded = np.zeros(
            (source_frame_count, *data.shape[1:]), dtype=data.dtype
        )
        for i, frame in enumerate(output_frames):
            if 0 <= int(frame) < source_frame_count:
                expanded[int(frame)] = data[i]
        return expanded

    def _add_or_update_image_layer(
        self,
        name: str,
        data: np.ndarray,
        metadata: dict,
        colormap: str,
    ) -> None:
        """Create or update an image layer while preserving world extent.
        TODO: refactor to a more general layer management utility if needed by other controllers.
        """
        source_shape = np.asarray(
            self.patari_controller.active_recon_layer.data
        ).shape
        target_shape = np.asarray(data).shape

        scale = list(self.patari_controller.active_recon_layer.scale)
        # Preserve world-space extent after grid reduction by rescaling pixel spacing.
        scale[-2] = (
            float(scale[-2])
            * float(source_shape[-2])
            / float(target_shape[-2])
        )
        scale[-1] = (
            float(scale[-1])
            * float(source_shape[-1])
            / float(target_shape[-1])
        )
        scale = tuple(scale)
        translate = tuple(self.patari_controller.active_recon_layer.translate)

        if name in self.viewer.layers and isinstance(
            self.viewer.layers[name], Image
        ):
            # Update in place so layer references and visibility state are kept.
            layer = self.viewer.layers[name]
            layer.data = data
            layer.scale = scale
            layer.translate = translate
            layer.metadata = metadata
            layer.colormap = colormap
            return

        self.viewer.add_image(
            data,
            name=name,
            scale=scale,
            translate=translate,
            colormap=colormap,
            opacity=1.0,
            blending="additive",
            metadata=metadata,
            units=self.patari_controller.active_recon_layer.units,
        )

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

        if dock.current_frame_only_checkbox.isChecked():
            current_frame = int(self.viewer.dims.current_step[0])
            if current_frame not in frame_numbers:
                dock.status_label.setText(
                    "Current frame is not reconstructed."
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
            self._extract_display_data(unmixed),
            output_frames,
            source_frame_count,
        )
        # Channel labels are used by downstream spectrum displays.
        self._add_or_update_image_layer(
            name=unmixed_name,
            data=unmixed_data,
            metadata=unmixed_metadata,
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
            )
            self._set_export_frame_attrs(thb, thb_export_attrs)
            thb_name = f"THb: {source_name}{suffix_part}{frame_part}"
            self._add_or_update_image_layer(
                name=thb_name,
                data=self._expand_to_source_frames(
                    self._extract_display_data(thb),
                    output_frames,
                    source_frame_count,
                ),
                metadata=thb_metadata,
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
            )
            self._set_export_frame_attrs(so2, so2_export_attrs)
            so2_name = f"sO2: {source_name}{suffix_part}{frame_part}"
            self._add_or_update_image_layer(
                name=so2_name,
                data=self._expand_to_source_frames(
                    self._extract_display_data(so2),
                    output_frames,
                    source_frame_count,
                ),
                metadata=so2_metadata,
                colormap="twilight_shifted",
            )
            self.patari_controller._derived_patato_objects[so2_name] = so2
            generated.append("so2")

        # Reassert ROI visibility priority after adding multiple result layers.
        self.patari_controller._ensure_shapes_layer_on_top()

        dock.status_label.setText(f"Finished: {', '.join(generated)}")
        logger.info("unmixing complete: %s", ", ".join(generated))
