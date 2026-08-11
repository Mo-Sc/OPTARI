"""Base class for task-specific controllers."""

import numpy as np

from napari.layers import Image

from patari.config import settings
from patari.patato_bridge import scale_from_patato_obj


class TaskControllerBase:
    """Minimal interface for task controllers.

    Each task controller (Analysis, Unmixing, etc)
    inherits from this.
    """

    image_units = ("dimensionless", "dimensionless", "mm", "mm")

    def __init__(self, parent_controller):
        """Initialize with reference to parent controller.

        Args:
            parent_controller: PatariController instance with viewer and session state.
        """
        self.patari_controller = parent_controller
        self.viewer = parent_controller.viewer

    def initialize_ui(self) -> None:
        """Initialize UI controls (populate lists, combos, etc). Override if needed."""
        pass

    def bind_events(self) -> None:
        """Connect signals to event handlers. Override if needed."""
        pass

    def unbind_events(self) -> None:
        """Disconnect signals. Override if needed."""
        pass

    def teardown(self) -> None:
        """Release resources (models, threads). Override if needed."""
        pass

    def refresh_ui(self) -> None:
        """Refresh controller-owned UI after application state changes."""
        pass

    @staticmethod
    def _expand_to_source_frames(
        data: np.ndarray,
        output_frames: list[int],
        source_frame_count: int,
    ) -> np.ndarray:
        """Pad sparse output frames back to the acquisition frame axis."""
        if data.shape[0] == source_frame_count:
            return data

        expanded = np.zeros(
            (source_frame_count, *data.shape[1:]), dtype=data.dtype
        )
        for i, frame in enumerate(output_frames):
            if i < data.shape[0] and 0 <= int(frame) < source_frame_count:
                expanded[int(frame)] = data[i]
        return expanded

    def _add_or_update_image_layer(
        self,
        name: str,
        data: np.ndarray,
        metadata: dict,
        patato_obj,
        colormap: str,
        offset_x_mm: float = 0.0,
        offset_z_mm: float = 0.0,
    ) -> None:
        """Create or update a PATATO-derived napari image layer."""

        scale = scale_from_patato_obj(
            patato_obj,
            settings.general.PA_FALLBACK_SCALE,
        )
        source_layer = self.patari_controller.active_recon_layer

        # translate means the position of the layer in the viewer
        translate = tuple(source_layer.translate) if source_layer is not None else None
        if translate is not None:
            translate = (
                *translate[:-2],
                translate[-2] + offset_z_mm,
                translate[-1] + offset_x_mm,
            )
        if name in self.viewer.layers and isinstance(self.viewer.layers[name], Image):
            # layer already exists, update its data and metadata
            layer = self.viewer.layers[name]
            layer.data = data
            layer.scale = scale
            if translate is not None:
                layer.translate = translate
            layer.metadata = metadata
            layer.colormap = colormap
            layer.units = self.image_units
        else:
            # layer does not exist, create a new one
            image_kwargs = {
                "name": name,
                "scale": scale,
                "colormap": colormap,
                "metadata": metadata,
                "opacity": 1.0,
                "blending": "multiplicative", # blending always multiplicative for better overlay
                "units": self.image_units,
            }
            if translate is not None:
                image_kwargs["translate"] = translate
            layer = self.viewer.add_image(data, **image_kwargs)

        layer.colorbar.visible = True
