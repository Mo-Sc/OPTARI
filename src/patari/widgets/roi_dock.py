from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from magicgui.widgets import Table
from qtpy.QtGui import QKeySequence
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QShortcut,
    QVBoxLayout,
    QWidget,
)

from patari.roi.roi_utils import (
    live_table_columns,
    saved_table_columns,
)


@dataclass
class RoiDock:
    widget: QWidget
    live_table: Table
    saved_table: Table
    save_button: QPushButton
    delete_button: QPushButton
    xlsx_button: QPushButton
    live_table_delete_shortcut: QShortcut


def create_roi_dock() -> RoiDock:
    live_columns = live_table_columns()
    saved_columns = saved_table_columns()
    df_live_empty = pd.DataFrame(columns=live_columns)
    df_saved_empty = pd.DataFrame(columns=saved_columns)

    live_table = Table(value=df_live_empty)
    saved_table = Table(value=df_saved_empty)

    save_button = QPushButton("Save ROI Data")
    save_button.setToolTip(
        "Save the selected shape's measurements to the Saved Analysis table "
        "(Shift+Ctrl+S / Shift+Cmd+S)"
    )
    delete_button = QPushButton("Delete ROI Data")
    delete_button.setToolTip("Delete the selected row(s) from the Saved Analysis table")
    xlsx_button = QPushButton("Export XLSX")

    # build Qt container for the bottom dock
    container = QWidget()
    layout = QHBoxLayout(container)

    live_panel = QWidget()
    live_layout = QVBoxLayout(live_panel)
    live_layout.addWidget(QLabel("Live Analysis"))
    live_layout.addWidget(live_table.native)

    delete_shortcut = QShortcut(QKeySequence.Delete, live_table.native)

    btn_panel = QWidget()
    btn_layout = QVBoxLayout(btn_panel)
    btn_layout.addWidget(QLabel(" "))
    btn_layout.addWidget(save_button)
    btn_layout.addWidget(delete_button)
    btn_layout.addWidget(xlsx_button)
    btn_layout.addStretch()

    saved_panel = QWidget()
    saved_layout = QVBoxLayout(saved_panel)
    saved_layout.addWidget(QLabel("Saved Analysis"))
    saved_layout.addWidget(saved_table.native)

    layout.addWidget(live_panel)
    layout.addWidget(btn_panel)
    layout.addWidget(saved_panel)

    container.setMinimumHeight(250)
    
    return RoiDock(
        widget=container,
        live_table=live_table,
        saved_table=saved_table,
        save_button=save_button,
        delete_button=delete_button,
        xlsx_button=xlsx_button,
        live_table_delete_shortcut=delete_shortcut,
    )
