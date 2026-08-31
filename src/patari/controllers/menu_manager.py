from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from qtpy.QtCore import QUrl
from qtpy.QtGui import QAction, QDesktopServices
from qtpy.QtWidgets import QMenu

from patari.widgets.settings_dialog import SettingsDialog

if TYPE_CHECKING:
    from patari.controllers.patari_controller import PatariController

logger = logging.getLogger(__name__)

DOCS_URL = "https://mo-sc.github.io/PATARI/"

# most napari menu items are useless in PATARI, and some can even break it. Hide them to avoid confusion.
# can be overridden by setting the PATARI_FULL_MENUS=1 env var.
HIDDEN_NAPARI_MENUS = ("plugins_menu", "layers_menu", "help_menu")
HIDDEN_FILE_ENTRIES = (
    "napari.window.file.open_files_dialog",
    "napari.window.file._image_from_clipboard",
    "napari.window.file.open_files_as_stack_dialog",
    "napari.window.file.open_folder_dialog",
    "napari/file/open_with_plugin",
    "napari/file/samples",
    "napari/file/new_layer",
    "napari/file/acquire",
    "napari/file/io_utilities",
)
HIDDEN_VIEW_ENTRIES = (
    "napari.window.view.toggle_ndisplay",
    "napari.viewer.toggle_synced_camera",
)


class MenuManager:
    """Add the PATARI menu to napari's menu bar and hide the entries PATARI doesnt support."""

    @staticmethod
    def setup(controller: "PatariController") -> None:
        window = controller.viewer.window
        if not hasattr(window, "main_menu"):
            logger.warning(
                "napari window exposes no main_menu; skipping PATARI menu setup."
            )
            return

        MenuManager._add_patari_menu(controller, window)

        if os.getenv("PATARI_FULL_MENUS") == "1":
            logger.info("PATARI_FULL_MENUS=1: leaving the napari menus untouched.")
            return

        MenuManager._prune_napari_menus(window)

    # ============ PATARI menu ============
    @staticmethod
    def _add_patari_menu(controller: "PatariController", window) -> None:
        menu = QMenu("PATARI", window._qt_window)

        settings_action = QAction("Settings...", menu)
        # macOS moves any action whose text mentions settings/preferences/options into the
        # application menu unless the role is pinned.
        settings_action.setMenuRole(QAction.NoRole)
        settings_action.triggered.connect(
            lambda: MenuManager._show_settings(controller)
        )
        menu.addAction(settings_action)

        menu.addSeparator()
        docs_action = QAction("Documentation", menu)
        docs_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(DOCS_URL))
        )
        menu.addAction(docs_action)

        window.main_menu.addMenu(menu)

    @staticmethod
    def _show_settings(controller: "PatariController") -> None:
        if controller.settings_dialog is None:
            qt_window = controller.viewer.window._qt_window
            controller.settings_dialog = SettingsDialog(qt_window)
        controller.settings_dialog.show()
        controller.settings_dialog.raise_()
        controller.settings_dialog.activateWindow()

    # ============ napari menu pruning ============
    @staticmethod
    def _prune_napari_menus(window) -> None:
        for attribute in HIDDEN_NAPARI_MENUS:
            menu = getattr(window, attribute, None)
            if menu is None:
                logger.debug("napari window has no %s to hide.", attribute)
                continue
            menu.menuAction().setVisible(False)

        for attribute, hidden_ids in (
            ("file_menu", HIDDEN_FILE_ENTRIES),
            ("view_menu", HIDDEN_VIEW_ENTRIES),
        ):
            menu = getattr(window, attribute, None)
            if menu is not None:
                MenuManager._hide_entries(menu, hidden_ids)

    @staticmethod
    def _hide_entries(menu, hidden_ids: tuple[str, ...]) -> None:
        for action in menu.actions():
            submenu = action.menu()
            # Command actions carry the id on the action, submenus carry it on the QMenu.
            identifier = (
                submenu.objectName() if submenu is not None else action.objectName()
            )
            if identifier in hidden_ids:
                action.setVisible(False)
