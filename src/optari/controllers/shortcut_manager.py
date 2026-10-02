import logging
import sys
from collections.abc import Callable

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
    """
    Manager for registering custom OPTARI keyboard shortcuts.
    """

    @classmethod
    def register_all(cls, controller) -> None:
        """Bind all custom keyboard shortcuts."""

        # 1. ROI Shortcuts
        cls._bind_shortcut_to_button(
            controller,
            shortcut_id="save_roi_data",
            button_getter=lambda c: c.roi.save_button,
            action_name="Save ROI Data",
        )

        # 2. Unmixing Shortcuts
        cls._bind_shortcut_to_button(
            controller,
            shortcut_id="run_unmixing",
            button_getter=lambda c: c.unmixing.run_button,
            action_name="Run Unmixing",
        )

        # 3. Segmentation Shortcuts
        cls._bind_shortcut_to_button(
            controller,
            shortcut_id="run_segmentation",
            button_getter=lambda c: c.segmentation.generate_tissue_segmentation_button,
            action_name="Run Segmentation",
        )

        logger.info("registered keyboard shortcuts: %s", SHORTCUTS)

    @classmethod
    def _bind_shortcut_to_button(
        cls,
        controller,
        shortcut_id: str,
        button_getter: Callable,
        action_name: str,
    ) -> None:
        """Bind keyboard shortcut to a dock's QPushButton."""
        shortcut = SHORTCUTS[shortcut_id]

        @controller.viewer.bind_key(shortcut, overwrite=True)
        def trigger_button(viewer):
            logger.info("shortcut %s triggered", shortcut)
            button = button_getter(controller)
            if button.isEnabled():
                button.click()
            else:
                logger.warning(
                    "shortcut %s ignored: %s button is disabled",
                    shortcut,
                    action_name,
                )
