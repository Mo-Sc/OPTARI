from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)


@dataclass
class UnmixingDock:
    widget: QWidget
    source_layer_label: QLabel
    preset_combo: QComboBox
    wavelengths_list: QListWidget
    select_all_wavelengths_button: QPushButton
    clear_wavelengths_button: QPushButton
    chromophores_list: QListWidget
    current_frame_only_checkbox: QCheckBox
    generate_thb_checkbox: QCheckBox
    generate_so2_checkbox: QCheckBox
    resolution_reduction_factor: QSpinBox
    suffix_edit: QLineEdit
    run_button: QPushButton
    status_label: QLabel


def create_unmixing_dock() -> UnmixingDock:
    widget = QWidget()
    shell_layout = QVBoxLayout(widget)
    shell_layout.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    shell_layout.addWidget(scroll)

    content_widget = QWidget()
    scroll.setWidget(content_widget)
    outer = QVBoxLayout(content_widget)

    source_box = QGroupBox("Source")
    source_form = QFormLayout(source_box)
    source_layer_label = QLabel("Select a PA reconstruction layer")
    source_form.addRow(source_layer_label)

    setup_box = QGroupBox("Unmixing Setup")
    setup_layout = QVBoxLayout(setup_box)

    preset_combo = QComboBox()

    wavelengths_list = QListWidget()
    wavelengths_list.setSelectionMode(QListWidget.NoSelection)
    wavelengths_list.setMinimumHeight(140)

    wavelength_button_row = QWidget()
    wavelength_button_layout = QHBoxLayout(wavelength_button_row)
    wavelength_button_layout.setContentsMargins(0, 0, 0, 0)
    select_all_wavelengths_button = QPushButton("Select all")
    clear_wavelengths_button = QPushButton("Clear")
    wavelength_button_layout.addWidget(select_all_wavelengths_button)
    wavelength_button_layout.addWidget(clear_wavelengths_button)

    chromophores_list = QListWidget()
    chromophores_list.setSelectionMode(QListWidget.NoSelection)
    chromophores_list.setMinimumHeight(140)

    current_frame_only_checkbox = QCheckBox("Use current frame only")
    current_frame_only_checkbox.setChecked(False)

    generate_thb_checkbox = QCheckBox("Generate THb layer")
    generate_thb_checkbox.setChecked(False)
    generate_so2_checkbox = QCheckBox("Generate sO2 layer")
    generate_so2_checkbox.setChecked(False)

    resolution_reduction_factor = QSpinBox()
    resolution_reduction_factor.setMinimum(1)
    resolution_reduction_factor.setMaximum(8)
    resolution_reduction_factor.setValue(3)

    suffix_edit = QLineEdit()
    suffix_edit.setPlaceholderText("optional suffix")
    suffix_edit.setClearButtonEnabled(True)

    setup_layout.addWidget(QLabel("Preset"))
    setup_layout.addWidget(preset_combo)

    setup_layout.addWidget(QLabel("Wavelengths"))
    setup_layout.addWidget(wavelengths_list)
    setup_layout.addWidget(wavelength_button_row)

    setup_layout.addWidget(QLabel("Chromophores"))
    setup_layout.addWidget(chromophores_list)

    setup_layout.addWidget(current_frame_only_checkbox)
    setup_layout.addWidget(generate_thb_checkbox)
    setup_layout.addWidget(generate_so2_checkbox)

    setup_layout.addWidget(QLabel("Resolution reduction factor"))
    setup_layout.addWidget(resolution_reduction_factor)

    setup_layout.addWidget(QLabel("Layer Suffix"))
    setup_layout.addWidget(suffix_edit)

    action_box = QGroupBox("Run")
    action_layout = QVBoxLayout(action_box)
    run_button = QPushButton("Run unmixing")
    status_label = QLabel("Select wavelengths and chromophores.")
    action_layout.addWidget(run_button)
    action_layout.addWidget(status_label)

    outer.addWidget(source_box)
    outer.addWidget(setup_box)
    outer.addWidget(action_box)
    outer.addStretch()

    return UnmixingDock(
        widget=widget,
        source_layer_label=source_layer_label,
        preset_combo=preset_combo,
        wavelengths_list=wavelengths_list,
        select_all_wavelengths_button=select_all_wavelengths_button,
        clear_wavelengths_button=clear_wavelengths_button,
        chromophores_list=chromophores_list,
        current_frame_only_checkbox=current_frame_only_checkbox,
        generate_thb_checkbox=generate_thb_checkbox,
        generate_so2_checkbox=generate_so2_checkbox,
        resolution_reduction_factor=resolution_reduction_factor,
        suffix_edit=suffix_edit,
        run_button=run_button,
        status_label=status_label,
    )
