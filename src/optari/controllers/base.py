"""Base class for task-specific controllers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from napari.layers import Image

from optari.config import settings
from optari.patato_bridge import scale_from_patato_obj
from optari.utils.tasks import download_then, start_task

if TYPE_CHECKING:
    from optari.controllers.optari_controller import OptariController


class TaskControllerBase:
    """Minimal interface for task controllers.

    Each task controller (Analysis, Unmixing, etc)
    inherits from this.

    A controller that runs heavy work implements three methods and gets the dock's
    Run button (`run_from_ui`) for free:

    - `_params_from_ui()` reads the dock into a params object, raising ValueError
      with a user-facing message when the run cannot be set up
    - `prepare(params)` validates and returns a `BackgroundStep`, raising ValueError
    - `publish(result, params)` adds the layers and returns the text shown after
      "Finished:"

    Batch mode builds params from a preset instead and calls the same `prepare` and
    `publish`, which is what keeps its numbers equal to the GUI's.
    """

    image_units = ("dimensionless", "dimensionless", "mm", "mm")

    def __init__(self, parent_controller: OptariController):
        """Initialize with reference to parent controller.

        Args:
            parent_controller: OptariController instance with viewer and session state.
        """
        self.optari_controller = parent_controller
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

    # ============ running a step from the dock ============
    def weights_to_fetch(self, params) -> tuple[Path, str | None] | None:
        """(local path, download url) a run needs on disk before it can start, or None."""
        return None

    def run_from_ui(self, dock) -> None:
        """The dock's Run button: params from widgets, fetch weights if needed, run, publish."""
        try:
            params = self._params_from_ui()
        except ValueError as exc:
            dock.status_label.setText(str(exc))
            return

        def run() -> None:
            try:
                step = self.prepare(params)
            except ValueError as exc:
                dock.status_label.setText(str(exc))
                return
            dock.status_label.setText(f"{step.desc}…")
            start_task(
                self.optari_controller,
                step,
                on_result=lambda result: dock.status_label.setText(
                    f"Finished: {self.publish(result, params)}"
                ),
                status_label=dock.status_label,
            )

        weights = self.weights_to_fetch(params)
        if weights is None:
            run()
            return
        download_then(self.optari_controller, *weights, dock.status_label, run)

    def _add_or_update_image_layer(
        self,
        name: str,
        data: np.ndarray,
        metadata: dict,
        patato_obj,
        colormap: str,
        translate: tuple[float, ...] | None = None,
    ) -> None:
        """Create or update a PATATO-derived napari image layer.

        `translate` places the layer absolutely in the viewer (mm, data axis order).
        When omitted, the layer inherits the active recon layer's position so that
        derived outputs stay aligned with the recon they were computed from.
        """

        scale = scale_from_patato_obj(
            patato_obj,
            settings.general.PA_FALLBACK_SCALE,
        )
        if translate is None:
            source_layer = self.optari_controller.active_recon_layer
            translate = (
                tuple(source_layer.translate) if source_layer is not None else None
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
                "auto_contrast": True,
                "units": self.image_units,
            }
            if translate is not None:
                image_kwargs["translate"] = translate
            layer = self.viewer.add_image(data, **image_kwargs)

        layer.colorbar.visible = True
