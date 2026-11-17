"""Unmixing controller: presets and running PATATO's spectral unmixing (+ THb/sO2)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator
from dataclasses import dataclass
from functools import partial
from math import ceil

import numpy as np
import patato as pat
from qtpy.QtCore import Qt
from skimage.transform import downscale_local_mean

from patato.io.attribute_tags import (
    HDF5Tags,
    ReconAttributeTags,
    UnmixingAttributeTags,
)
from patato.unmixing.spectra import SPECTRA_NAMES
from optari.controllers.base import TaskControllerBase
from optari.utils.tasks import BackgroundStep
from optari.patato_bridge import (
    display_data_from_patato_obj,
    expand_to_acquisition_frames,
    layer_colormap,
    pa_layer_metadata,
)
from optari.utils.presets import PresetStore
from optari.utils.setup import get_user_unmixing_presets_dir
from optari.widgets.dock_helpers import (
    add_checkable_item,
    checked_items,
    list_items,
    populate_preset_combo,
    set_checked,
)

logger = logging.getLogger(__name__)

# Unlike PATATO's reconstruction/preprocessing, SpectralUnmixer.run has no internal batch
# loop or GPU/ONNX call. We chunk it ourselves to allow progress updates and cancellation.
UNMIXING_CHUNK_FRAMES = 4


def resolve_unmixing_wavelengths(
    preset: dict, available: list[int]
) -> list[int]:
    """Which of a scan's *available* wavelengths a preset selects.

    Presets name either an explicit list or an inclusive range, and both are resolved
    per scan rather than per preset: two scans in the same study can be acquired at
    different wavelengths, and a range must not invent one the scan does not have.
    """
    explicit = preset.get(UnmixingAttributeTags.UNMIXING_WAVELENGTHS)
    if explicit is not None:
        wanted = {int(w) for w in explicit}
        return sorted(w for w in available if w in wanted)

    wavelength_range = preset.get(UnmixingAttributeTags.WAVELENGTH_RANGE)
    if wavelength_range is not None and len(wavelength_range) == 2:
        start, end = int(wavelength_range[0]), int(wavelength_range[1])
        return sorted(w for w in available if start <= w <= end)

    return []


def validate_unmixing_spectra(
    wavelengths: list[int], chromophores: list[str]
) -> None:
    """Raise a user-facing error when a spectrum has no values at a wavelength."""
    wavelength_array = np.asarray(wavelengths, dtype=float)
    missing = {
        chromophore: [
            wavelength
            for wavelength, value in zip(
                wavelengths,
                SPECTRA_NAMES[chromophore].get_spectrum(wavelength_array),
            )
            if not np.isfinite(value)
        ]
        for chromophore in chromophores
    }
    missing = {
        chromophore: values
        for chromophore, values in missing.items()
        if values
    }
    if missing:
        details = "; ".join(
            f"{chromophore}: {', '.join(f'{wavelength} nm' for wavelength in wavelengths)}"
            for chromophore, wavelengths in missing.items()
        )
        raise ValueError(f"No spectrum data is available for {details}.")


@dataclass
class UnmixParams:
    """Everything one unmixing run needs, resolved against a loaded scan."""

    recon_for_run: object
    source_layer_name: str
    source_layer_metadata: dict
    source_frame_count: int
    wavelengths: list[int]
    chromophores: list[str]
    output_frames: list[int]
    # napari translate of the output layers on the image axes (mm), see UnmixParams.build
    translate_yx: tuple[float, float]
    reduce_factor: int = 1
    suffix: str = ""
    generate_thb: bool = False
    generate_so2: bool = False
    current_frame_id: int | None = None

    @property
    def frame_mode(self) -> str:
        """Whether the run covers the current frame or all frames."""
        return "current" if self.current_frame_id is not None else "all"

    @property
    def name_stem(self) -> str:
        """Base name for output layers, derived from the source recon layer, suffix and frame."""
        source_name = self.source_layer_name.replace("Recon: ", "")
        suffix_part = f"_{self.suffix}" if self.suffix else ""
        # Encode the acquisition-frame index when only a single frame is unmixed.
        frame_part = (
            f"_F{self.current_frame_id}"
            if self.current_frame_id is not None
            else ""
        )
        return f"{source_name}{suffix_part}{frame_part}"

    @property
    def settings(self) -> dict:
        """Settings dict stored as metadata on output layers, e.g. for presets and export."""
        return {
            "wavelengths": self.wavelengths,
            "chromophores": self.chromophores,
            "resolution_reduction_factor": self.reduce_factor,
            "suffix": self.suffix,
            "frame_mode": self.frame_mode,
            "frames": self.output_frames,
            "generate_thb": self.generate_thb,
            "generate_so2": self.generate_so2,
        }

    @classmethod
    def build(
        cls,
        controller,
        *,
        wavelengths: list[int],
        chromophores: list[str],
        reduce_factor: int = 1,
        suffix: str = "",
        generate_thb: bool = False,
        generate_so2: bool = False,
        frame_id: int | None = None,
    ) -> "UnmixParams":
        """Resolve an unmixing setup against the active reconstruction layer.

        Raises ValueError, message safe to show the user, when it cannot run here.
        """
        active_layer = controller.active_recon_layer
        if active_layer is None:
            raise ValueError("Select a PA reconstruction layer.")
        recon = controller.patato_objects.get(active_layer.name)
        if recon is None:
            raise ValueError("Source layer must be a reconstruction.")
        if not wavelengths:
            raise ValueError("Select at least one wavelength.")
        if not chromophores:
            raise ValueError("Select at least one chromophore.")
        validate_unmixing_spectra(wavelengths, chromophores)

        frame_numbers = list(
            active_layer.metadata.get("frames") or range(recon.shape[0])
        )
        recon_for_run = recon
        output_frames = frame_numbers
        if frame_id is not None:
            if frame_id not in frame_numbers:
                raise ValueError("Selected frame is not reconstructed.")
            # PATATO expects a contiguous slice, then we remap to acquisition frame ids.
            recon_idx = frame_numbers.index(frame_id)
            recon_for_run = recon[recon_idx : recon_idx + 1]
            output_frames = [frame_id]

        return cls(
            recon_for_run=recon_for_run,
            source_layer_name=active_layer.name,
            source_layer_metadata=dict(active_layer.metadata),
            source_frame_count=int(active_layer.data.shape[0]),
            # A coarse pixel averages a reduce_factor-wide block of the source's pixels
            # and belongs at the block's centre, (reduce_factor - 1) / 2 source pixels
            # past its first pixel.
            translate_yx=tuple(
                float(t + (reduce_factor - 1) / 2 * s)
                for t, s in zip(
                    active_layer.translate[-2:], active_layer.scale[-2:]
                )
            ),
            wavelengths=wavelengths,
            chromophores=chromophores,
            output_frames=output_frames,
            reduce_factor=int(reduce_factor),
            suffix=suffix.strip(),
            generate_thb=bool(generate_thb),
            generate_so2=bool(generate_so2),
            current_frame_id=frame_id,
        )

    @classmethod
    def from_preset(
        cls, preset: dict, controller, *, frame_id: int | None = None
    ):
        """Resolve an unmixing preset against the loaded scan's own wavelengths."""
        active_layer = controller.active_recon_layer
        if active_layer is None:
            raise ValueError("Select a PA reconstruction layer.")
        available = [
            int(w) for w in active_layer.metadata.get("wavelengths") or []
        ]
        wavelengths = resolve_unmixing_wavelengths(preset, available)
        if not wavelengths:
            raise ValueError(
                "None of the preset's wavelengths were acquired in this scan "
                f"(scan has {available or 'none'})."
            )
        chromophores = list(preset.get(UnmixingAttributeTags.SPECTRA, []))
        # THb/sO2 need the haemoglobin pair, same rule the dock enforces.
        hb_pair = {"Hb", "HbO2"} <= set(chromophores)
        return cls.build(
            controller,
            wavelengths=wavelengths,
            chromophores=chromophores,
            reduce_factor=int(
                preset.get(UnmixingAttributeTags.RESOLUTION_REDUCE, 1)
            ),
            suffix=str(preset.get(UnmixingAttributeTags.SUFFIX, "")),
            generate_thb=hb_pair
            and bool(preset.get(UnmixingAttributeTags.COMPUTE_THB, True)),
            generate_so2=hb_pair
            and bool(preset.get(UnmixingAttributeTags.COMPUTE_SO2, True)),
            frame_id=frame_id,
        )


def _block_average(recon, factor: int):
    """Average *factor*-wide pixel blocks of *recon* into a coarser Reconstruction.

    Done here rather than by PATATO's unmixer (causes misalignment).
    Blocks are tiled from the image's top-left corner as the viewer shows it, which
    UnmixParams.build's translate relies on. downscale_local_mean would pad a partial
    edge block with zeros, so it is cropped off first and the FOV shrinks with it.
    """
    data = np.asarray(recon.raw_data)  # (frames, wavelengths, z, y, x)
    z, y, x = data.shape[2:]
    fz, fy, fx = (min(factor, n) for n in (z, y, x))
    # z is shown flipped (display_data_from_patato_obj), so its partial block is cut at
    # the start: the viewer's bottom edge, like x's at the right edge.
    cropped = data[:, :, z % fz :, : y - y % fy, : x - x % fx]
    coarse = downscale_local_mean(cropped, (1, 1, fz, fy, fx)).astype(
        np.float32
    )
    attributes = dict(recon.attributes)
    fov_tags = (
        ReconAttributeTags.X_FIELD_OF_VIEW,
        ReconAttributeTags.Y_FIELD_OF_VIEW,
        ReconAttributeTags.Z_FIELD_OF_VIEW,
    )
    n_pixel_tags = (
        ReconAttributeTags.X_NUMBER_OF_PIXELS,
        ReconAttributeTags.Y_NUMBER_OF_PIXELS,
        ReconAttributeTags.Z_NUMBER_OF_PIXELS,
    )
    for fov_tag, n_tag, axis in zip(fov_tags, n_pixel_tags, (-1, -2, -3)):
        attributes[fov_tag] *= cropped.shape[axis] / data.shape[axis]
        attributes[n_tag] = coarse.shape[axis]
    return pat.Reconstruction(
        coarse,
        recon.ax_1_labels,
        field_of_view=[attributes[tag] for tag in fov_tags],
        attributes=attributes,
        hdf5_sub_name=recon.hdf5_sub_name,
    )


def _unmix_frames(
    recon_for_run,
    pa_data,
    wavelengths: list[int],
    chromophores: list[str],
    reduce_factor: int,
    suffix: str,
    generate_thb: bool,
    generate_so2: bool,
    chunk_frames: int,
) -> Generator[
    None,
    None,
    tuple[
        pat.ImageSequence, pat.ImageSequence | None, pat.ImageSequence | None
    ],
]:
    """Unmix *recon_for_run* in frame chunks, yielding once per finished chunk.

    Runs in a worker thread, so it must not touch Qt or napari. THb/sO2 (when requested)
    are computed per chunk.
    """
    unmixer = pat.SpectralUnmixer(
        chromophores=chromophores,
        wavelengths=np.array(wavelengths, dtype=float),
        algorithm_id=suffix,
    )
    thb_calc = pat.THbCalculator(algorithm_id=suffix) if generate_thb else None
    so2_calc = (
        pat.SO2Calculator(algorithm_id=suffix, nan_invalid=True)
        if generate_so2
        else None
    )

    unmixed_chunks, thb_chunks, so2_chunks = [], [], []
    for start in range(0, int(recon_for_run.shape[0]), chunk_frames):
        frames = recon_for_run[start : start + chunk_frames]
        if reduce_factor > 1:
            frames = _block_average(frames, reduce_factor)
        unmixed_chunk, _, _ = unmixer.run(frames, pa_data)
        unmixed_chunks.append(unmixed_chunk)
        if thb_calc is not None:
            thb_chunk, _, _ = thb_calc.run(unmixed_chunk, pa_data)
            thb_chunks.append(thb_chunk)
        if so2_calc is not None:
            so2_chunk, _, _ = so2_calc.run(unmixed_chunk, pa_data)
            so2_chunks.append(so2_chunk)
        yield

    unmixed = pat.ImageSequence.concat(unmixed_chunks)
    thb = pat.ImageSequence.concat(thb_chunks) if thb_chunks else None
    so2 = pat.ImageSequence.concat(so2_chunks) if so2_chunks else None
    return unmixed, thb, so2


class UnmixingController(TaskControllerBase):
    """Run spectral unmixing and add as layers."""

    preset_fallback_name = "unmixing_preset"

    def __init__(self, parent_controller):
        """Initialize the unmixing preset store."""
        super().__init__(parent_controller)
        self.preset_store = PresetStore(get_user_unmixing_presets_dir())

    def _signal_bindings(self) -> list[tuple[object, Callable]]:
        """Unmixing dock signals."""
        dock = self.optari_controller.unmixing
        return [
            (dock.preset_combo.currentIndexChanged, self.on_preset_changed),
            (dock.chromophores_list.itemChanged, self.on_chromophores_changed),
            (
                dock.select_all_wavelengths_button.clicked,
                self.on_select_all_wavelengths_clicked,
            ),
            (
                dock.clear_wavelengths_button.clicked,
                self.on_clear_wavelengths_clicked,
            ),
            (dock.run_button.clicked, self.on_run_unmixing_clicked),
            (dock.save_preset_button.clicked, self.on_save_preset_clicked),
            (dock.remove_preset_button.clicked, self.on_remove_preset_clicked),
        ]

    def _checked_wavelengths(self) -> list[int]:
        return [
            item.data(Qt.UserRole)
            for item in checked_items(
                self.optari_controller.unmixing.wavelengths_list
            )
        ]

    def _checked_chromophores(self) -> list[str]:
        return [
            item.text()
            for item in checked_items(
                self.optari_controller.unmixing.chromophores_list
            )
        ]

    def initialize_ui(self) -> None:
        """Initialize preset, chromophore, and wavelength controls once."""
        dock = self.optari_controller.unmixing

        populate_preset_combo(dock.preset_combo, self.preset_store)

        if dock.chromophores_list.count() == 0:
            for name in sorted(SPECTRA_NAMES.keys()):
                add_checkable_item(dock.chromophores_list, name)

        self.refresh_ui()
        self.on_chromophores_changed()

    @property
    def preset_dock(self):
        return self.optari_controller.unmixing

    def _preset_settings_from_ui(self) -> dict:
        dock = self.optari_controller.unmixing
        return {
            UnmixingAttributeTags.RESOLUTION_REDUCE: dock.resolution_reduction_factor.value(),
            UnmixingAttributeTags.UNMIXING_WAVELENGTHS: self._checked_wavelengths(),
            UnmixingAttributeTags.SPECTRA: self._checked_chromophores(),
            UnmixingAttributeTags.COMPUTE_THB: dock.generate_thb_checkbox.isChecked(),
            UnmixingAttributeTags.COMPUTE_SO2: dock.generate_so2_checkbox.isChecked(),
            UnmixingAttributeTags.SUFFIX: dock.suffix_edit.text().strip(),
        }

    def refresh_ui(self) -> None:
        """Refresh source-dependent controls from the active layer."""
        dock = self.optari_controller.unmixing
        active_recon_layer = self.optari_controller.active_recon_layer

        if (
            active_recon_layer is None
            or active_recon_layer.metadata["pa_kind"] != "recon"
        ):
            dock.source_layer_label.setText("Select a PA reconstruction layer")
            dock.wavelengths_list.clear()
            # disable unmixing button when no valid source is active
            dock.run_button.setEnabled(False)
            return

        dock.source_layer_label.setText(active_recon_layer.name)

        # Enable unmixing button
        dock.run_button.setEnabled(not self.optari_controller.task_running)

        wavelengths = active_recon_layer.metadata.get("wavelengths") or []
        source_name = active_recon_layer.name
        last_source = dock.widget.property("_unmixing_source_name")

        # Keep manual wavelength selections while the same source stays active.
        if last_source == source_name and dock.wavelengths_list.count() > 0:
            return

        dock.widget.setProperty("_unmixing_source_name", source_name)
        dock.wavelengths_list.clear()
        for w in wavelengths:
            add_checkable_item(
                dock.wavelengths_list, f"{int(w)} nm", int(w), checked=True
            )

        self.on_preset_changed()

    def on_select_all_wavelengths_clicked(self) -> None:
        """Select all source wavelengths in the list widget."""
        set_checked(
            self.optari_controller.unmixing.wavelengths_list, lambda item: True
        )

    def on_clear_wavelengths_clicked(self) -> None:
        """Clear all source wavelength selections in the list widget."""
        set_checked(
            self.optari_controller.unmixing.wavelengths_list,
            lambda item: False,
        )

    def _apply_preset(self, settings: dict) -> None:
        dock = self.optari_controller.unmixing
        # Every value read before the first widget changes, so a bad preset changes nothing
        reduce_factor = int(
            settings.get(UnmixingAttributeTags.RESOLUTION_REDUCE, 1)
        )
        spectra = set(settings.get(UnmixingAttributeTags.SPECTRA, []))
        # Same resolution as a batch run, so the dock shows what a run would use.
        selected_wavelengths = set(
            resolve_unmixing_wavelengths(
                settings,
                [
                    item.data(Qt.UserRole)
                    for item in list_items(dock.wavelengths_list)
                ],
            )
        )
        compute_so2 = settings.get(UnmixingAttributeTags.COMPUTE_SO2, True)
        compute_thb = settings.get(UnmixingAttributeTags.COMPUTE_THB, True)
        suffix = str(settings.get(UnmixingAttributeTags.SUFFIX, ""))

        dock.resolution_reduction_factor.setValue(max(1, reduce_factor))
        dock.suffix_edit.setText(suffix)
        set_checked(
            dock.chromophores_list, lambda item: item.text() in spectra
        )
        set_checked(
            dock.wavelengths_list,
            lambda item: item.data(Qt.UserRole) in selected_wavelengths,
        )
        dock.generate_so2_checkbox.setChecked(bool(compute_so2))
        dock.generate_thb_checkbox.setChecked(bool(compute_thb))
        self.on_chromophores_changed()

    def on_chromophores_changed(self) -> None:
        """
        Enable THb and sO2 options only when Hb and HbO2 are selected.
        so2 is activated by default
        """
        dock = self.optari_controller.unmixing
        hb_pair_available = {"Hb", "HbO2"} <= set(self._checked_chromophores())

        dock.generate_so2_checkbox.setEnabled(hb_pair_available)
        dock.generate_thb_checkbox.setEnabled(hb_pair_available)
        if not hb_pair_available:
            dock.generate_so2_checkbox.setChecked(False)
            dock.generate_thb_checkbox.setChecked(False)

    @staticmethod
    def _set_export_attrs(
        image_sequence,
        *,
        source_layer_name: str,
        output_frames: list[int],
        channel_labels: list[str],
        pa_kind: str,
        frame_mode: str,
        parameter: str | None = None,
    ) -> None:
        """Attributes the HDF5 export writes with an unmixing output, and a reload reads back."""
        attrs = image_sequence.attributes
        attrs["frames"] = np.asarray(output_frames, dtype=int)
        attrs["source_layer"] = str(source_layer_name)
        attrs["axis1_labels"] = [str(label) for label in channel_labels]
        attrs["pa_kind"] = str(pa_kind)
        attrs["source_frame_mode"] = str(frame_mode)
        if parameter is not None:
            attrs["parameter"] = str(parameter)

    # ============ run: params -> prepare -> publish ============
    def _params_from_ui(self) -> UnmixParams:
        """Build run parameters from the dock. Raises ValueError with a user-facing message."""
        dock = self.optari_controller.unmixing
        frame_id = (
            int(self.viewer.dims.current_step[0])
            if dock.current_frames_radio.isChecked()
            else None
        )
        return UnmixParams.build(
            self.optari_controller,
            wavelengths=self._checked_wavelengths(),
            chromophores=self._checked_chromophores(),
            reduce_factor=int(dock.resolution_reduction_factor.value()),
            suffix=dock.suffix_edit.text(),
            generate_thb=dock.generate_thb_checkbox.isChecked(),
            generate_so2=dock.generate_so2_checkbox.isChecked(),
            frame_id=frame_id,
        )

    def prepare(self, params: UnmixParams) -> BackgroundStep:
        """Return the work to run for *params*."""
        n_chunks = ceil(len(params.output_frames) / UNMIXING_CHUNK_FRAMES)
        logger.info(
            "running unmixing for %s with %s wavelength(s), %s chromophore(s), reduce=%s, "
            "in %s chunk(s) of %s",
            params.source_layer_name,
            len(params.wavelengths),
            len(params.chromophores),
            params.reduce_factor,
            n_chunks,
            UNMIXING_CHUNK_FRAMES,
        )
        return BackgroundStep(
            func=partial(
                _unmix_frames,
                params.recon_for_run,
                self.optari_controller.pa_data,
                params.wavelengths,
                params.chromophores,
                params.reduce_factor,
                params.suffix,
                params.generate_thb,
                params.generate_so2,
                UNMIXING_CHUNK_FRAMES,
            ),
            total=n_chunks,
            desc="Unmixing",
        )

    def _publish_one(
        self,
        image,
        params: UnmixParams,
        *,
        prefix,
        channel_labels,
        pa_kind,
        colormap,
        parameter=None,
    ) -> str:
        """Add one unmixing output as a layer and register it for export."""
        source = params.source_layer_metadata
        metadata = pa_layer_metadata(
            pa_kind=pa_kind,
            channel_labels=channel_labels,
            frames=params.output_frames,
            scan_timestamps=source["timestamps"],
            acquisition_start=source.get("acquisition_start"),
            settings=params.settings,
            filepath=source.get("filepath"),
            scan_name=source.get("scan_name"),
            source_layer=params.source_layer_name,
            parameter=parameter,
        )
        self._set_export_attrs(
            image,
            source_layer_name=params.source_layer_name,
            output_frames=params.output_frames,
            channel_labels=channel_labels,
            pa_kind=pa_kind,
            frame_mode=params.frame_mode,
            parameter=parameter,
        )
        name = f"{prefix}: {params.name_stem}"
        self._add_or_update_image_layer(
            name=name,
            data=expand_to_acquisition_frames(
                display_data_from_patato_obj(image),
                params.output_frames,
                params.source_frame_count,
            ),
            metadata=metadata,
            patato_obj=image,
            colormap=colormap,
            translate_yx=params.translate_yx,
        )
        self.optari_controller.derived_patato_objects[name] = image
        return name

    def publish(self, result, params: UnmixParams) -> str:
        """Add the finished unmixed/THb/sO2 layers. Runs on the main thread."""
        unmixed, thb, so2 = result

        names = [
            self._publish_one(
                unmixed,
                params,
                prefix="Unmixed",
                # Channel labels are used by downstream spectrum displays.
                channel_labels=list(map(str, unmixed.ax_1_labels)),
                pa_kind="unmixed",
                colormap=layer_colormap(HDF5Tags.UNMIXED),
            )
        ]
        if thb is not None:
            names.append(
                self._publish_one(
                    thb,
                    params,
                    prefix="THb",
                    channel_labels=["thb"],
                    pa_kind="unmixed_param",
                    colormap=layer_colormap(HDF5Tags.THB),
                    parameter="thb",
                )
            )
        if so2 is not None:
            names.append(
                self._publish_one(
                    so2,
                    params,
                    prefix="sO2",
                    channel_labels=["so2"],
                    pa_kind="unmixed_param",
                    colormap=layer_colormap(HDF5Tags.SO2),
                    parameter="so2",
                )
            )

        # Reassert ROI visibility priority after adding multiple result layers.
        self.optari_controller.ensure_shapes_layer_on_top()
        logger.info("unmixing complete: %s", ", ".join(names))
        return ", ".join(names)

    def on_run_unmixing_clicked(self) -> None:
        """Run unmixing from the dock's Run button."""
        self.run_from_ui(self.optari_controller.unmixing)
