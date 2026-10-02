from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from qtpy.QtCore import QLocale, Qt
from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QInputDialog,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from optari.utils.presets import PresetStore


@dataclass
class DockShell:
    widget: QWidget
    content_widget: QWidget
    content_layout: QVBoxLayout
    scroll_area: QScrollArea | None


def create_frame_scope_controls() -> (
    tuple[QWidget, QRadioButton, QRadioButton]
):
    """Create the shared current/all frames radio-button control."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    current_frames_radio = QRadioButton("Selected Frame")
    all_frames_radio = QRadioButton("All Frames")
    current_frames_radio.setChecked(True)

    group = QButtonGroup(container)
    group.setExclusive(True)
    group.addButton(current_frames_radio)
    group.addButton(all_frames_radio)

    layout.addWidget(QLabel("Scope"))
    layout.addWidget(current_frames_radio)
    layout.addWidget(all_frames_radio)
    return container, current_frames_radio, all_frames_radio


# helpers for preset management
def create_preset_controls() -> (
    tuple[QComboBox, QPushButton, QPushButton, QWidget]
):
    """Create the shared preset selector and save/remove action row."""
    preset_combo = QComboBox()
    save_preset_button = QPushButton("Save Preset")
    remove_preset_button = QPushButton("Remove Preset")

    actions = QWidget()
    actions_layout = QHBoxLayout(actions)
    actions_layout.setContentsMargins(0, 0, 0, 0)
    actions_layout.addWidget(save_preset_button)
    actions_layout.addWidget(remove_preset_button)
    return preset_combo, save_preset_button, remove_preset_button, actions


def populate_preset_combo(combo: QComboBox, store: PresetStore) -> None:
    """Populate a preset combo and select its first entry."""
    combo.blockSignals(True)
    try:
        combo.clear()
        for preset_path in store.list_paths():
            combo.addItem(preset_path.stem, userData=preset_path)
        if combo.count() > 0:
            combo.setCurrentIndex(0)
    finally:
        combo.blockSignals(False)


def prompt_preset_name(
    parent: QWidget, combo: QComboBox, fallback: str
) -> str | None:
    """Ask for a new preset name, returning ``None`` when cancelled."""
    name, accepted = QInputDialog.getText(
        parent,
        "Save Preset",
        "Preset name:",
        text=combo.currentText() or fallback,
    )
    return name if accepted else None


def add_preset_to_combo(combo: QComboBox, preset_path: Path) -> None:
    """Add a saved preset and select it."""
    combo.addItem(preset_path.stem, userData=preset_path)
    combo.setCurrentIndex(combo.count() - 1)


def remove_selected_preset(
    combo: QComboBox, store: PresetStore
) -> tuple[Path | None, bool]:
    """Delete the selected preset and remove it from the combo."""
    preset_path = combo.currentData()
    if preset_path is None:
        return None, False
    removed = store.delete(preset_path)
    if removed:
        combo.removeItem(combo.currentIndex())
    return preset_path, removed


# Helpers for right-side form docks in UiManager._tabify_docks().
def create_right_dock_shell(
    *,
    enable_scroll: bool = True,
    horizontal_scroll_policy: Qt.ScrollBarPolicy = Qt.ScrollBarAlwaysOff,
    vertical_scroll_policy: Qt.ScrollBarPolicy = Qt.ScrollBarAsNeeded,
) -> DockShell:
    """Create the shell used by right-side docks with optional scrolling."""
    widget = QWidget()
    shell_layout = QVBoxLayout(widget)
    shell_layout.setContentsMargins(0, 0, 0, 0)

    content_widget = QWidget()
    content_layout = QVBoxLayout(content_widget)

    if not enable_scroll:
        shell_layout.addWidget(content_widget)
        return DockShell(
            widget=widget,
            content_widget=content_widget,
            content_layout=content_layout,
            scroll_area=None,
        )

    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(horizontal_scroll_policy)
    scroll_area.setVerticalScrollBarPolicy(vertical_scroll_policy)
    scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    scroll_area.setWidget(content_widget)
    shell_layout.addWidget(scroll_area)

    return DockShell(
        widget=widget,
        content_widget=content_widget,
        content_layout=content_layout,
        scroll_area=scroll_area,
    )


# Helpers for bottom analysis docks in UiManager._tabify_docks().
def create_bottom_dock_header(
    layout: QVBoxLayout,
    *,
    status_text: str,
    button_text: str = "Refresh",
) -> tuple[QLabel, QPushButton]:
    """Add the standard status label and primary action row for bottom docks."""
    status_label = QLabel(status_text)
    status_label.setWordWrap(True)
    action_button = QPushButton(button_text)
    layout.addWidget(status_label)
    layout.addWidget(action_button)
    return status_label, action_button


def create_bottom_plot_strip(
    *,
    spacing: int = 8,
) -> tuple[QScrollArea, QWidget]:
    """Create the horizontally scrolling plot strip used by bottom analysis docks."""
    plots_container = QWidget()
    plots_layout = QHBoxLayout(plots_container)
    plots_layout.setContentsMargins(0, 0, 0, 0)
    plots_layout.setSpacing(spacing)

    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setWidget(plots_container)
    return scroll_area, plots_container


@dataclass
class RoiPlotsDock:
    """Base for bottom docks that show one plot per ROI in a scrolling strip."""

    widget: QWidget
    refresh_button: QPushButton
    scroll_area: QScrollArea
    plots_container: QWidget
    status_label: QLabel

    @classmethod
    def create(cls, *, status_text: str, refresh_tooltip: str):
        """Build the dock: status line, Refresh button, and the plot strip."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        status_label, refresh_button = create_bottom_dock_header(
            layout, status_text=status_text
        )
        refresh_button.setToolTip(refresh_tooltip)
        scroll_area, plots_container = create_bottom_plot_strip()
        layout.addWidget(scroll_area, stretch=1)
        return cls(
            widget=widget,
            refresh_button=refresh_button,
            scroll_area=scroll_area,
            plots_container=plots_container,
            status_label=status_label,
        )


def create_bottom_single_plot_container() -> QWidget:
    """Create the single-plot container used by the time-analysis bottom dock."""
    plot_container = QWidget()
    plot_layout = QVBoxLayout(plot_container)
    plot_layout.setContentsMargins(0, 0, 0, 0)
    return plot_container


def create_range_edits(
    *,
    placeholder: str = "(unset)",
    minimum: float | None = None,
    maximum: float | None = None,
    decimals: int = 6,
) -> tuple[QLineEdit, QLineEdit]:
    """Create a pair of min/max numeric edits with consistent validation and UX."""

    def _new_numeric_edit() -> QLineEdit:
        edit = QLineEdit()
        validator = QDoubleValidator()
        validator.setLocale(QLocale.c())
        validator.setDecimals(decimals)
        if minimum is not None:
            validator.setBottom(minimum)
        if maximum is not None:
            validator.setTop(maximum)
        edit.setValidator(validator)
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        return edit

    return _new_numeric_edit(), _new_numeric_edit()


# helpers for lists of checkboxes (chromophores, wavelengths, segmentation classes)
def add_checkable_item(
    list_widget: QListWidget, text: str, data=None, *, checked: bool = False
) -> None:
    """Append a checkbox entry, with *data* stored under ``Qt.UserRole``."""
    item = QListWidgetItem(text)
    item.setData(Qt.UserRole, data)
    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
    list_widget.addItem(item)


def list_items(list_widget: QListWidget) -> list[QListWidgetItem]:
    """All entries, in display order."""
    return [list_widget.item(i) for i in range(list_widget.count())]


def checked_items(list_widget: QListWidget) -> list[QListWidgetItem]:
    """The checked entries, in display order."""
    return [
        item
        for item in list_items(list_widget)
        if item.checkState() == Qt.Checked
    ]


def set_checked(
    list_widget: QListWidget, should_check: Callable[[QListWidgetItem], bool]
) -> None:
    """Check exactly the entries *should_check* accepts."""
    for item in list_items(list_widget):
        item.setCheckState(Qt.Checked if should_check(item) else Qt.Unchecked)
