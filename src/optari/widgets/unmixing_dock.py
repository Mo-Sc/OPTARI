from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from .dock_helpers import (
    create_frame_scope_controls,
    create_preset_controls,
    create_right_dock_shell,
)


@dataclass
class UnmixingDock:
    widget: QWidget
    source_layer_label: QLabel
    preset_combo: QComboBox
    save_preset_button: QPushButton
    remove_preset_button: QPushButton
    wavelengths_list: QListWidget
    select_all_wavelengths_button: QPushButton
    clear_wavelengths_button: QPushButton
    chromophores_list: QListWidget
    current_frames_radio: QRadioButton
    all_frames_radio: QRadioButton
    generate_thb_checkbox: QCheckBox
    generate_so2_checkbox: QCheckBox
    resolution_reduction_factor: QSpinBox
    suffix_edit: QLineEdit
    run_button: QPushButton
    status_label: QLabel


def create_unmixing_dock() -> UnmixingDock:
    widget, outer = create_right_dock_shell()

    source_box = QGroupBox("Source")
    source_form = QFormLayout(source_box)
    source_layer_label = QLabel("Select a PA reconstruction layer")
    source_layer_label.setWordWrap(True)
    source_form.addRow(source_layer_label)

    setup_box = QGroupBox("Unmixing Setup")
    setup_layout = QVBoxLayout(setup_box)

    (
        preset_combo,
        save_preset_button,
        remove_preset_button,
        preset_actions,
    ) = create_preset_controls()
    preset_combo.setToolTip(
        "Selecting a preset loads its wavelength, chromophore, and layer settings"
    )
    remove_preset_button.setToolTip(
        "Permanently delete the selected preset file"
    )

    wavelengths_list = QListWidget()
    wavelengths_list.setSelectionMode(QListWidget.NoSelection)
    wavelengths_list.setMinimumHeight(140)
    wavelengths_list.setToolTip(
        "Available wavelengths are determined by the source layer"
    )

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
    chromophores_list.setToolTip(
        "Hb and HbO2 must be checked to enable the THb/sO2 layers below"
    )

    generate_thb_checkbox = QCheckBox("Generate THb layer")
    generate_thb_checkbox.setChecked(False)
    generate_thb_checkbox.setToolTip(
        "Adds a total-hemoglobin layer (requires Hb and HbO2 both selected above)"
    )
    generate_so2_checkbox = QCheckBox("Generate sO2 layer")
    generate_so2_checkbox.setChecked(False)
    generate_so2_checkbox.setToolTip(
        "Adds an oxygen-saturation layer (requires Hb and HbO2 both selected above)"
    )

    resolution_reduction_factor = QSpinBox()
    resolution_reduction_factor.setMinimum(1)
    resolution_reduction_factor.setMaximum(8)
    resolution_reduction_factor.setValue(3)
    resolution_reduction_factor.setToolTip(
        "Downsamples the reconstruction before unmixing; 1 = full resolution"
    )

    suffix_edit = QLineEdit()
    suffix_edit.setPlaceholderText("optional suffix")
    suffix_edit.setClearButtonEnabled(True)

    setup_layout.addWidget(QLabel("Preset"))
    setup_layout.addWidget(preset_combo)
    setup_layout.addWidget(preset_actions)

    setup_layout.addWidget(QLabel("Wavelengths"))
    setup_layout.addWidget(wavelengths_list)
    setup_layout.addWidget(wavelength_button_row)

    setup_layout.addWidget(QLabel("Chromophores"))
    setup_layout.addWidget(chromophores_list)

    setup_layout.addWidget(generate_thb_checkbox)
    setup_layout.addWidget(generate_so2_checkbox)

    setup_layout.addWidget(QLabel("Resolution reduction factor"))
    setup_layout.addWidget(resolution_reduction_factor)

    setup_layout.addWidget(QLabel("Layer Suffix"))
    setup_layout.addWidget(suffix_edit)

    action_box = QGroupBox("Run")
    action_layout = QVBoxLayout(action_box)
    frame_scope_row, current_frames_radio, all_frames_radio = (
        create_frame_scope_controls()
    )
    run_button = QPushButton("Run Unmixing")
    run_button.setToolTip(
        "Requires an active PA reconstruction layer, and at least one wavelength and "
        "chromophore selected (Shift+Ctrl+U / Shift+Cmd+U)"
    )
    status_label = QLabel("Select wavelengths and chromophores.")
    status_label.setWordWrap(True)
    action_layout.addWidget(frame_scope_row)
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
        save_preset_button=save_preset_button,
        remove_preset_button=remove_preset_button,
        wavelengths_list=wavelengths_list,
        select_all_wavelengths_button=select_all_wavelengths_button,
        clear_wavelengths_button=clear_wavelengths_button,
        chromophores_list=chromophores_list,
        current_frames_radio=current_frames_radio,
        all_frames_radio=all_frames_radio,
        generate_thb_checkbox=generate_thb_checkbox,
        generate_so2_checkbox=generate_so2_checkbox,
        resolution_reduction_factor=resolution_reduction_factor,
        suffix_edit=suffix_edit,
        run_button=run_button,
        status_label=status_label,
    )
