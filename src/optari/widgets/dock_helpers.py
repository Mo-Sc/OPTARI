"""Building blocks the docks share: preset rows, frame scope radios, plot strips."""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from qtpy.QtCore import QRegularExpression, Qt
from qtpy.QtGui import QRegularExpressionValidator
from qtpy.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from optari.utils.presets import PresetStore


def show_status_error(label: QLabel, message: str) -> None:
    """Show *message* on a dock's status label in red, the style of every error."""
    label.setText(f'<span style="color:red">{html.escape(message)}</span>')


def create_frame_scope_controls() -> tuple[QWidget, QRadioButton, QRadioButton]:
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
def create_preset_controls() -> tuple[QComboBox, QPushButton, QPushButton, QWidget]:
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


def prompt_preset_name(parent: QWidget, combo: QComboBox, fallback: str) -> str | None:
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


# helpers for the right-side form docks
def create_right_dock_shell() -> tuple[QWidget, QVBoxLayout]:
    """The dock widget and the layout its content goes in, scrolling vertically."""
    widget = QWidget()
    shell_layout = QVBoxLayout(widget)
    shell_layout.setContentsMargins(0, 0, 0, 0)

    content_widget = QWidget()
    content_layout = QVBoxLayout(content_widget)

    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    scroll_area.setWidget(content_widget)
    shell_layout.addWidget(scroll_area)
    return widget, content_layout


# helpers for the bottom analysis docks
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


def create_bottom_plot_strip() -> tuple[QScrollArea, QWidget]:
    """Create the horizontally scrolling plot strip used by bottom analysis docks."""
    plots_container = QWidget()
    plots_layout = QHBoxLayout(plots_container)
    plots_layout.setContentsMargins(0, 0, 0, 0)
    plots_layout.setSpacing(8)

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

    def clear(self) -> None:
        """Remove every plot and the status text."""
        layout = self.plots_container.layout()
        while layout.count():
            plot = layout.takeAt(0).widget()
            plot.setParent(None)  # hidden now, not only once deleteLater runs
            plot.deleteLater()
        self.status_label.setText("")


def create_number_edit(*, placeholder: str = "", signed: bool = True) -> QLineEdit:
    """A line edit for a decimal number, read with ``parse_float_input``.

    Point and comma are both accepted as the decimal separator, whatever the system
    locale: QDoubleValidator follows the locale, so on a German system it accepts
    only "2,5", which float() rejects, and with the C locale the comma key does nothing.
    """
    sign = "-?" if signed else ""
    edit = QLineEdit()
    edit.setValidator(
        QRegularExpressionValidator(
            QRegularExpression(rf"^{sign}\d*([.,]\d*)?([eE][-+]?\d*)?$")
        )
    )
    edit.setPlaceholderText(placeholder)
    edit.setClearButtonEnabled(True)
    return edit


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
    return [item for item in list_items(list_widget) if item.checkState() == Qt.Checked]


def set_checked(
    list_widget: QListWidget, should_check: Callable[[QListWidgetItem], bool]
) -> None:
    """Check exactly the entries *should_check* accepts."""
    for item in list_items(list_widget):
        item.setCheckState(Qt.Checked if should_check(item) else Qt.Unchecked)
