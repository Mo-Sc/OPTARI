from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from napari.layers import Image, Layer
from napari.viewer import Viewer


@dataclass(frozen=True)
class SelectedLayerResult:
    layer: Image
    reason: str


def iter_image_layers(viewer: Viewer) -> Iterable[Image]:
    for layer in viewer.layers:
        if isinstance(layer, Image):
            yield layer


def get_selected_layer(viewer: Viewer) -> Layer | None:
    """Return the currently selected layer (napari selection), if any."""
    try:
        selection = viewer.layers.selection
    except Exception:
        return None

    for layer in selection:
        return layer
    return None


def is_pa_image_layer(layer: Layer) -> bool:
    return isinstance(layer, Image) and layer.metadata.get("type") == "pa"


def resolve_active_image_layer(
    viewer: Viewer,
    *,
    require_pa: bool = True,
) -> SelectedLayerResult | None:
    """Resolve the active layer using the *currently selected layer* rule.

    Selection precedence:
    1) If a selected layer exists and matches requirements, use it.
    2) Otherwise, fall back to the first matching image layer in the stack.

    Parameters
    ----------
    viewer:
        Napari viewer.
    require_pa:
        If True, only allow Image layers with metadata["type"] == "pa".
        If False, allow any Image layer.
    """
    selected = get_selected_layer(viewer)

    def ok(layer: Layer) -> bool:
        if not isinstance(layer, Image):
            return False
        if require_pa:
            return is_pa_image_layer(layer)
        return True

    if selected is not None and ok(selected):
        return SelectedLayerResult(layer=selected, reason="selected")

    for layer in iter_image_layers(viewer):
        if ok(layer):
            return SelectedLayerResult(layer=layer, reason="fallback")

    return None
