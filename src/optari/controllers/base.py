"""Base class for task-specific controllers."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from napari.layers import Image

from optari.config import settings
from optari.patato_bridge import (
    LAYER_NAME_ATTR,
    SETTINGS_ATTR,
    TRANSLATE_ATTR,
    scale_from_patato_obj,
)
from optari.utils.metadata import json_default
from optari.utils.tasks import download_then, start_task
from optari.widgets.dock_helpers import (
    add_preset_to_combo,
    prompt_preset_name,
    remove_selected_preset,
)

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

    A controller whose dock has a preset row (combo, Save, Remove) sets `preset_store`
    and `preset_fallback_name`, and implements:

    - `preset_dock`, the dock holding the row and a `status_label`
    - `_preset_settings_from_ui()`, the dock's settings as a preset dict, raising
      ValueError with a user-facing message
    - `_apply_preset(settings)`, put a loaded preset into the dock, raising on a
      malformed one before changing anything where it can
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

    def _signal_bindings(self) -> list[tuple[object, Callable]]:
        """Every (signal, handler) pair this controller owns. Override if needed.

        Declared once and walked in both directions, so a binding cannot be connected
        but forgotten on teardown.
        """
        return []

    def bind_events(self) -> None:
        """Connect this controller's dock signals to their handlers."""
        for signal, handler in self._signal_bindings():
            signal.connect(handler)

    def unbind_events(self) -> None:
        """Disconnect everything bind_events connected."""
        for signal, handler in self._signal_bindings():
            signal.disconnect(handler)

    def teardown(self) -> None:
        """Release resources (models, threads). Override if needed."""
        pass

    def refresh_ui(self) -> None:
        """Refresh controller-owned UI after application state changes."""
        pass

    # ============ presets ============
    def on_preset_changed(self) -> None:
        """Apply the preset selected in the dock's combo."""
        dock = self.preset_dock
        preset_path = dock.preset_combo.currentData()
        if preset_path is None:
            return
        try:
            self._apply_preset(self.preset_store.load(preset_path))
        # Preset files are user-edited JSON, so any field may have any type
        except (TypeError, ValueError, KeyError, OSError) as exc:
            dock.status_label.setText(f"Could not apply preset: {exc}")

    def on_save_preset_clicked(self) -> None:
        """Save the dock's current settings as a new user preset."""
        dock = self.preset_dock
        try:
            preset_settings = self._preset_settings_from_ui()
        except ValueError as exc:
            dock.status_label.setText(f"Could not save preset: {exc}")
            return
        name = prompt_preset_name(
            dock.widget, dock.preset_combo, self.preset_fallback_name
        )
        if name is None:
            return
        try:
            preset_path = self.preset_store.save(name, preset_settings)
        except (ValueError, OSError) as exc:
            dock.status_label.setText(f"Could not save preset: {exc}")
            return
        # Selecting it applies it through on_preset_changed
        add_preset_to_combo(dock.preset_combo, preset_path)
        dock.status_label.setText(f"Saved preset: {preset_path.name}")

    def on_remove_preset_clicked(self) -> None:
        """Delete the preset selected in the dock's combo."""
        dock = self.preset_dock
        try:
            removed_path, removed = remove_selected_preset(
                dock.preset_combo, self.preset_store
            )
        except OSError as exc:
            dock.status_label.setText(f"Could not remove preset: {exc}")
            return
        if removed_path is None:
            dock.status_label.setText("Select a preset to remove.")
        elif not removed:
            dock.status_label.setText(f"Preset not found: {removed_path.name}")
        else:
            dock.status_label.setText(f"Removed preset: {removed_path.name}")

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

            def finished(result) -> None:
                # Replaced on success. If publish raises, napari reports the error and
                # the label must not keep saying the step is still running.
                dock.status_label.setText("Failed, see the log")
                dock.status_label.setText(
                    f"Finished: {self.publish(result, params)}"
                )

            start_task(
                self.optari_controller,
                step,
                on_result=finished,
                on_error=dock.status_label.setText,
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
                tuple(source_layer.translate)
                if source_layer is not None
                else None
            )
        # so an exported scan reopens with the same layers in the same place
        patato_obj.attributes[LAYER_NAME_ATTR] = name
        patato_obj.attributes[SETTINGS_ATTR] = json.dumps(
            metadata["settings"], default=json_default
        )
        if translate is not None:
            patato_obj.attributes[TRANSLATE_ATTR] = [
                float(t) for t in translate[-2:]
            ]
        if name in self.viewer.layers and isinstance(
            self.viewer.layers[name], Image
        ):
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
                "blending": "multiplicative",  # blending always multiplicative for better overlay
                "auto_contrast": True,
                "units": self.image_units,
            }
            if translate is not None:
                image_kwargs["translate"] = translate
            layer = self.viewer.add_image(data, **image_kwargs)

        layer.colorbar.visible = True
