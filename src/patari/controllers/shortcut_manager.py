import logging
import sys

logger = logging.getLogger(__name__)

# workaoround for cross-platform cmd/ctrl key in shortcuts
CMD_CTRL = "Meta" if sys.platform == "darwin" else "Control"

# --- SHORTCUT REGISTRY ---
SHORTCUTS = {
    "save_roi_data": f"{CMD_CTRL}-Shift-S", # mimics "Save ROI Data" button, saves all selected ROIs to the saved table
}


class ShortcutManager:
    """manager for registering custom PATARI keyboard shortcuts."""

    @classmethod
    def register_all(cls, controller) -> None:
        """bind all custom keyboard shortcuts."""
        cls._setup_roi_shortcuts(controller)
        # cls._setup_scan_shortcuts(controller)

    @classmethod
    def _setup_roi_shortcuts(cls, controller) -> None:
        """Binds custom keyboard shortcuts related to ROI table operations."""
        viewer = controller.viewer

        @viewer.bind_key(SHORTCUTS["save_roi_data"], overwrite=True)
        def _save_roi_data(v):
            logger.info("PATARI Shortcut: Control-Shift-S triggered.")
            
            save_button = controller.roi.save_button
            # Make sure ROIs are present (should mean button is enabled)
            if save_button.enabled: 
                save_button.clicked()
            else:
                logger.warning("PATARI Shortcut: Control-Shift-S ignored: Save button is disabled.")

    @classmethod
    def _setup_scan_shortcuts(cls, controller) -> None:
        # future scan navigation shortcuts
        pass