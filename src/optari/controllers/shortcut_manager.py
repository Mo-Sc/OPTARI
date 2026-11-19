"""OPTARI's keyboard shortcuts, each of which presses a dock button."""

import logging
import sys

from qtpy.QtWidgets import QPushButton

logger = logging.getLogger(__name__)

# workaround for cross-platform cmd/ctrl key in shortcuts
CMD_CTRL = "Meta" if sys.platform == "darwin" else "Control"

# napari key names. Each button's tooltip shows its shortcut from here, so this is the
# only place a key is written down.
SHORTCUTS = {
    "save_roi_data": f"{CMD_CTRL}-Shift-S",
    "run_unmixing": f"{CMD_CTRL}-Shift-U",
    "run_segmentation": f"{CMD_CTRL}-Shift-T",
}


class ShortcutManager:
    """Binds OPTARI's keyboard shortcuts to the dock buttons they press."""

    def __init__(self, controller):
        self.controller = controller

    def register_all(self) -> None:
        """Bind all custom keyboard shortcuts. The docks must exist already."""
        controller = self.controller
        self._bind_shortcut_to_button(
            "save_roi_data", controller.roi_dock.save_button, "Save ROI Data"
        )
        self._bind_shortcut_to_button(
            "run_unmixing", controller.unmixing_dock.run_button, "Run Unmixing"
        )
        self._bind_shortcut_to_button(
            "run_segmentation",
            controller.segmentation_dock.generate_tissue_segmentation_button,
            "Run Segmentation",
        )
        logger.info("registered keyboard shortcuts: %s", SHORTCUTS)

    def _bind_shortcut_to_button(
        self, shortcut_id: str, button: QPushButton, action_name: str
    ) -> None:
        """Bind a shortcut to a dock button and name it in the button's tooltip."""
        shortcut = SHORTCUTS[shortcut_id]
        keys = (
            shortcut.replace("Meta", "Cmd").replace("Control", "Ctrl").replace("-", "+")
        )
        button.setToolTip(f"{button.toolTip()} ({keys})")

        @self.controller.viewer.bind_key(shortcut, overwrite=True)
        def trigger_button(viewer):
            logger.info("shortcut %s triggered", shortcut)
            if button.isEnabled():
                button.click()
            else:
                logger.warning(
                    "shortcut %s ignored: %s button is disabled",
                    shortcut,
                    action_name,
                )
