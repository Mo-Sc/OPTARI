import logging
import sys

from qtpy.QtWidgets import QPushButton

logger = logging.getLogger(__name__)

# workaround for cross-platform cmd/ctrl key in shortcuts
CMD_CTRL = "Meta" if sys.platform == "darwin" else "Control"

# --- SHORTCUT REGISTRY ---
SHORTCUTS = {
    "save_roi_data": f"{CMD_CTRL}-Shift-S",  # triggers "Save ROI Data" button
    "run_unmixing": f"{CMD_CTRL}-Shift-U",  # triggers unmixing with current settings
    "run_segmentation": f"{CMD_CTRL}-Shift-T",  # triggers segmentation with current settings
}


class ShortcutManager:
    """Binds OPTARI's keyboard shortcuts to the dock buttons they press."""

    def __init__(self, controller):
        self.controller = controller

    def register_all(self) -> None:
        """Bind all custom keyboard shortcuts. The docks must exist already."""
        controller = self.controller
        self._bind_shortcut_to_button(
            "save_roi_data", controller.roi.save_button, "Save ROI Data"
        )
        self._bind_shortcut_to_button(
            "run_unmixing", controller.unmixing.run_button, "Run Unmixing"
        )
        self._bind_shortcut_to_button(
            "run_segmentation",
            controller.segmentation.generate_tissue_segmentation_button,
            "Run Segmentation",
        )
        logger.info("registered keyboard shortcuts: %s", SHORTCUTS)

    def _bind_shortcut_to_button(
        self, shortcut_id: str, button: QPushButton, action_name: str
    ) -> None:
        """Bind a keyboard shortcut to a dock's QPushButton."""
        shortcut = SHORTCUTS[shortcut_id]

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
