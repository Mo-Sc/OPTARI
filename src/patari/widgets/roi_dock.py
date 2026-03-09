from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from magicgui.widgets import PushButton, Table
from qtpy.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from patari.config import dtype_map


@dataclass
class RoiDock:
    widget: QWidget
    live_table: Table
    saved_table: Table
    save_button: PushButton
    delete_button: PushButton
    csv_button: PushButton
    hdf5_button: PushButton


def create_roi_dock() -> RoiDock:
    df_empty = pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

    live_table = Table(value=df_empty.copy())
    saved_table = Table(value=df_empty.copy())

    save_button = PushButton(text="Save ROI")
    delete_button = PushButton(text="Delete Saved")
    csv_button = PushButton(text="Export XLSX")
    hdf5_button = PushButton(text="Save to scan")

    # build Qt container for the bottom dock
    container = QWidget()
    layout = QHBoxLayout(container)

    live_panel = QWidget()
    live_layout = QVBoxLayout(live_panel)
    live_layout.addWidget(QLabel("Live ROIs"))
    live_layout.addWidget(live_table.native)

    btn_panel = QWidget()
    btn_layout = QVBoxLayout(btn_panel)
    btn_layout.addWidget(QLabel(" "))
    btn_layout.addWidget(save_button.native)
    btn_layout.addWidget(delete_button.native)
    btn_layout.addWidget(csv_button.native)
    btn_layout.addWidget(hdf5_button.native)
    btn_layout.addStretch()

    saved_panel = QWidget()
    saved_layout = QVBoxLayout(saved_panel)
    saved_layout.addWidget(QLabel("Saved ROIs"))
    saved_layout.addWidget(saved_table.native)

    layout.addWidget(live_panel)
    layout.addWidget(btn_panel)
    layout.addWidget(saved_panel)

    container.setMinimumHeight(300)

    return RoiDock(
        widget=container,
        live_table=live_table,
        saved_table=saved_table,
        save_button=save_button,
        delete_button=delete_button,
        csv_button=csv_button,
        hdf5_button=hdf5_button,
    )
