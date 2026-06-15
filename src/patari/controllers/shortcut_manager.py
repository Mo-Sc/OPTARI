import logging
import sys

logger = logging.getLogger(__name__)

# workaoround for cross-platform cmd/ctrl key in shortcuts
CMD_CTRL = "Meta" if sys.platform == "darwin" else "Control"

# --- SHORTCUT REGISTRY ---
SHORTCUTS = {
    "save_roi_data": f"{CMD_CTRL}-Shift-S", # mimics "Save ROI Data" button, saves all selected ROIs to the saved table
    "run_unmixing": f"{CMD_CTRL}-Shift-U", # trigger unmixing with current settings (if source layer is selected and presets are loaded)
}


class ShortcutManager:
    """
    manager for registering custom PATARI keyboard shortcuts.
    Note that depending on the widget, buttons can be implemented as Qt QPushButtons or magicgui PushButtons.
    (button.click() and isEnabled() vs button.clicked() and button.enabled)
    """

    @classmethod
    def register_all(cls, controller) -> None:
        """bind all custom keyboard shortcuts."""
        cls._setup_roi_shortcuts(controller)
        cls._setup_unmixing_shortcuts(controller)
        # cls._setup_scan_shortcuts(controller)
        logger.info(f"PATARI: Registered custom keyboard shortcuts: {SHORTCUTS}")

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
    def _setup_unmixing_shortcuts(cls, controller) -> None:
        """Binds custom keyboard shortcuts related to unmixing operations."""
        viewer = controller.viewer

        @viewer.bind_key(SHORTCUTS["run_unmixing"], overwrite=True)
        def _run_unmixing(v):
            logger.info("PATARI Shortcut: Control-Shift-U triggered.")
            
            run_button = controller.unmixing.run_button
            # Make sure unmixing can be run (should mean button is enabled)
            if run_button.isEnabled():
                run_button.click()
            else:
                logger.warning("PATARI Shortcut: Control-Shift-U ignored: Run Unmixing button is disabled.")

    @classmethod
    def _setup_scan_shortcuts(cls, controller) -> None:
        # future scan navigation shortcuts
        pass