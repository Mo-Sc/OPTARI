import logging
import sys

logger = logging.getLogger(__name__)

# workaround for cross-platform cmd/ctrl key in shortcuts
CMD_CTRL = "Meta" if sys.platform == "darwin" else "Control"

# --- SHORTCUT REGISTRY ---
SHORTCUTS = {
    "save_roi_data": f"{CMD_CTRL}-Shift-S",    # triggers "Save ROI Data" button
    "run_unmixing": f"{CMD_CTRL}-Shift-U",     # triggers unmixing with current settings
    "run_segmentation": f"{CMD_CTRL}-Shift-T", # triggers segmentation with current settings
}


class ShortcutManager:
    """
    Manager for registering custom OPTARI keyboard shortcuts.
    Automatically handles both Qt QPushButtons and magicgui PushButtons.
    """

    @classmethod
    def register_all(cls, controller) -> None:
        """Bind all custom keyboard shortcuts."""
        
        # 1. ROI Shortcuts
        cls._bind_shortcut_to_button(
            controller, 
            shortcut_id="save_roi_data", 
            button_getter=lambda c: c.roi.save_button, 
            action_name="Save ROI Data"
        )
        
        # 2. Unmixing Shortcuts
        cls._bind_shortcut_to_button(
            controller, 
            shortcut_id="run_unmixing", 
            button_getter=lambda c: c.unmixing.run_button, 
            action_name="Run Unmixing"
        )
        
        # 3. Segmentation Shortcuts
        cls._bind_shortcut_to_button(
            controller, 
            shortcut_id="run_segmentation", 
            button_getter=lambda c: c.segmentation.generate_tissue_segmentation_button, 
            action_name="Run Segmentation"
        )
        
        logger.info("registered keyboard shortcuts: %s", SHORTCUTS)

    @classmethod
    def _bind_shortcut_to_button(cls, controller, shortcut_id: str, button_getter: callable, action_name: str) -> None:
        """
        Bind keyboard shortcut to a UI button.
        depending on the widget, buttons can be implemented as Qt QPushButtons or magicgui PushButtons.
        (button.click() and isEnabled() vs button.clicked() and button.enabled)
        """
        viewer = controller.viewer
        shortcut = SHORTCUTS.get(shortcut_id)

        @viewer.bind_key(shortcut, overwrite=True)
        def trigger_button(v):

            logger.info("shortcut %s triggered", shortcut)
            
            button = button_getter(controller)
            
            # Handles the API differences between magicgui and native Qt widgets
            is_active = button.enabled if hasattr(button, "enabled") else button.isEnabled()
            
            if is_active:
                if hasattr(button, "click"):
                    # Qt: .click()
                    button.click()
                else:
                    # magicgui: .clicked())
                    button.clicked()
            else:
                logger.warning("shortcut %s ignored: %s button is disabled", shortcut, action_name)
