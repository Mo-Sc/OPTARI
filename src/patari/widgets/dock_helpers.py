from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import QLocale, Qt
from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


@dataclass
class DockShell:
    widget: QWidget
    content_widget: QWidget
    content_layout: QVBoxLayout
    scroll_area: QScrollArea | None


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