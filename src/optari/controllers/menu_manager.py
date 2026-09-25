from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Callable

from qtpy.QtCore import QUrl
from qtpy.QtGui import QAction, QDesktopServices
from qtpy.QtWidgets import QMenu

from optari.config import settings
from optari.widgets.dock_helpers import DOCK_LABELS
from optari.widgets.batch_dialog import BatchDialog
from optari.widgets.settings_dialog import SettingsDialog

if TYPE_CHECKING:
    from optari.controllers.optari_controller import OptariController

logger = logging.getLogger(__name__)

DOCS_URL = "https://mo-sc.github.io/OPTARI/"

# most napari menu items are useless in OPTARI, and some can even break it. Hide them to avoid confusion.
# can be overridden by setting the OPTARI_FULL_MENUS=1 env var.
HIDDEN_NAPARI_MENUS = ("plugins_menu", "layers_menu", "help_menu", "window_menu")
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
    "napari.scene.toggle_ndisplay",
    "napari.scene.toggle_synced_camera",
)

# How to reach each dock widget named in DOCK_LABELS, from a OptariController. The OPTARI-owned
# docks are attributes set by UiManager.setup_docks(). Layer Controls/List are napari's own,
# reached through its private QtViewer.
_DOCK_RESOLVERS: dict[str, Callable[["OptariController"], object]] = {
    "Scan Browser": lambda c: c._scan_browser_dock_widget,
    "Active Slice Info": lambda c: c._info_dock_widget,
    "Tabular": lambda c: c._roi_dock_widget,
    "Time Analysis": lambda c: c._time_analysis_dock_widget,
    "Histogram": lambda c: c._histograms_dock_widget,
    "Spectrum": lambda c: c._spectrum_dock_widget,
    "Annotation": lambda c: c._annotation_dock_widget,
    "Segmentation": lambda c: c._segmentation_dock_widget,
    "Unmixing": lambda c: c._unmixing_dock_widget,
    "Reconstruction": lambda c: c._reconstruction_dock_widget,
    "Layer Controls": lambda c: c.viewer.window._qt_viewer.dockLayerControls,
    "Layer List": lambda c: c.viewer.window._qt_viewer.dockLayerList,
}


def _iter_dock_widgets(controller: "OptariController"):
    """Yield (label, dock_widget) for every dock in DOCK_LABELS that currently resolves."""
    for label in DOCK_LABELS:
        try:
            dock_widget = _DOCK_RESOLVERS[label](controller)
        except AttributeError:
            dock_widget = None
        if dock_widget is not None:
            yield label, dock_widget


class MenuManager:
    """Add the OPTARI menu to napari's menu bar and hide the entries OPTARI doesnt support."""

    @staticmethod
    def setup(controller: "OptariController") -> None:
        window = controller.viewer.window
        if not hasattr(window, "main_menu"):
            logger.warning(
                "napari window exposes no main_menu; skipping OPTARI menu setup."
            )
            return

        MenuManager._apply_default_dock_visibility(controller)
        MenuManager._add_optari_menu(controller, window)

        if os.getenv("OPTARI_FULL_MENUS") == "1":
            logger.info("OPTARI_FULL_MENUS=1: leaving the napari menus untouched.")
            return

        MenuManager._prune_napari_menus(window)

    # ============ OPTARI menu ============
    @staticmethod
    def _add_optari_menu(controller: "OptariController", window) -> None:
        menu = QMenu("OPTARI", window._qt_window)

        settings_action = QAction("Settings", menu)
        # macOS moves any action whose text mentions settings/preferences/options into the
        # application menu unless the role is pinned.
        settings_action.setMenuRole(QAction.NoRole)
        settings_action.triggered.connect(
            lambda: MenuManager._show_settings(controller)
        )
        menu.addAction(settings_action)

        batch_action = QAction("Batch Mode", menu)
        batch_action.setMenuRole(QAction.NoRole)
        batch_action.triggered.connect(lambda: MenuManager._show_batch(controller))
        menu.addAction(batch_action)

        menu.addSeparator()
        docs_action = QAction("Documentation", menu)
        docs_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(DOCS_URL))
        )
        menu.addAction(docs_action)

        menu.addSeparator()
        MenuManager._add_dock_toggles(controller, menu)

        window.main_menu.addMenu(menu)

    @staticmethod
    def _add_dock_toggles(controller: "OptariController", menu: QMenu) -> None:
        """Add a Docks submenu with a checkable show/hide toggle per dock.

        Reuses QDockWidget's own toggleViewAction(), the same mechanism napari uses for its own
        Window menu so visibility stays in sync even when a dock is closed some other way.
        """
        docks_menu = menu.addMenu("Docks")
        for label, dock_widget in _iter_dock_widgets(controller):
            action = dock_widget.toggleViewAction()
            action.setText(label)
            docks_menu.addAction(action)

    @staticmethod
    def _apply_default_dock_visibility(controller: "OptariController") -> None:
        """Force each dock's visibility to the Settings > Docks defaults.

        Runs on every launch and overrides whatever napari's own session-restore
        (save_window_state) would otherwise show
        """
        defaults = settings.general.DEFAULT_VISIBLE_DOCKS
        for label, dock_widget in _iter_dock_widgets(controller):
            dock_widget.setVisible(bool(int(defaults.get(label, 1))))

    @staticmethod
    def _show_settings(controller: "OptariController") -> None:
        if controller.settings_dialog is None:
            qt_window = controller.viewer.window._qt_window
            controller.settings_dialog = SettingsDialog(qt_window)
        controller.settings_dialog.show()
        controller.settings_dialog.raise_()
        controller.settings_dialog.activateWindow()

    # ============ napari menu pruning ============
    @staticmethod
    def _show_batch(controller: "OptariController") -> None:
        if controller.batch_dialog is None:
            qt_window = controller.viewer.window._qt_window
            controller.batch_dialog = BatchDialog(qt_window, controller)
        controller.batch_dialog.show()
        controller.batch_dialog.raise_()
        controller.batch_dialog.activateWindow()

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
