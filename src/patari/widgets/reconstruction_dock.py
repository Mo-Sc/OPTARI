from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .dock_helpers import (
    create_frame_scope_controls,
    create_preset_controls,
    create_right_dock_shell,
)


# speed of sound slider bounds
SPEED_OF_SOUND_MIN = 1400
SPEED_OF_SOUND_MAX = 1600
SPEED_OF_SOUND_DEFAULT = 1525


@dataclass
class ReconstructionDock:
    widget: QWidget
    scan_status_label: QLabel
    preset_combo: QComboBox
    current_frames_radio: QRadioButton
    all_frames_radio: QRadioButton
    all_settings_button: QToolButton
    settings_edit: QPlainTextEdit
    apply_preset_button: QPushButton
    save_preset_button: QPushButton
    remove_preset_button: QPushButton
    speed_of_sound_slider: QSlider
    speed_of_sound_value_label: QLabel
    suffix_edit: QLineEdit
    run_button: QPushButton
    status_label: QLabel


def create_reconstruction_dock(*, enable_scroll: bool = True) -> ReconstructionDock:
    shell = create_right_dock_shell(enable_scroll=enable_scroll)
    widget = shell.widget
    outer = shell.content_layout

    source_box = QGroupBox("Source")
    source_form = QFormLayout(source_box)
    scan_status_label = QLabel("No scan loaded")
    source_form.addRow(scan_status_label)

    setup_box = QGroupBox("Reconstruction Setup")
    setup_layout = QVBoxLayout(setup_box)

    (
        preset_combo,
        save_preset_button,
        remove_preset_button,
        preset_actions,
    ) = create_preset_controls()
    preset_combo.setToolTip("Selecting a preset loads its settings into the editor below")
    remove_preset_button.setToolTip("Permanently delete the selected preset file")

    all_settings_button = QToolButton()
    all_settings_button.setText("Show all settings")
    all_settings_button.setCheckable(True)
    all_settings_button.setChecked(False)
    all_settings_button.setArrowType(Qt.RightArrow)

    settings_edit = QPlainTextEdit()
    settings_edit.setPlaceholderText("JSON reconstruction settings")
    settings_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
    settings_edit.setVisible(False)
    settings_edit.setToolTip(
        "Edits here must be confirmed with Apply Preset — Run stays disabled until then"
    )
    apply_preset_button = QPushButton("Apply Preset")
    apply_preset_button.setVisible(False)
    apply_preset_button.setToolTip(
        "Apply the edited settings for this run only (does not save them to the preset file)"
    )
    settings_actions = QHBoxLayout()
    settings_actions.addWidget(apply_preset_button)

    speed_of_sound_slider = QSlider(Qt.Horizontal)
    speed_of_sound_slider.setMinimum(SPEED_OF_SOUND_MIN)
    speed_of_sound_slider.setMaximum(SPEED_OF_SOUND_MAX)
    speed_of_sound_slider.setValue(SPEED_OF_SOUND_DEFAULT)
    speed_of_sound_slider.setToolTip(
        "Overrides the preset's speed of sound for this run only — does not affect "
        "other layers or the saved preset"
    )
    speed_of_sound_value_label = QLabel(f"{SPEED_OF_SOUND_DEFAULT} m/s")
    speed_of_sound_row = QWidget()
    speed_of_sound_row_layout = QHBoxLayout(speed_of_sound_row)
    speed_of_sound_row_layout.setContentsMargins(0, 0, 0, 0)
    speed_of_sound_row_layout.addWidget(speed_of_sound_slider)
    speed_of_sound_row_layout.addWidget(speed_of_sound_value_label)

    suffix_edit = QLineEdit()
    suffix_edit.setPlaceholderText("optional suffix")
    suffix_edit.setClearButtonEnabled(True)

    setup_layout.addWidget(QLabel("Preset"))
    setup_layout.addWidget(preset_combo)
    setup_layout.addWidget(preset_actions)

    setup_layout.addWidget(QLabel("Speed of sound"))
    setup_layout.addWidget(speed_of_sound_row)

    setup_layout.addWidget(all_settings_button)
    setup_layout.addWidget(settings_edit)
    setup_layout.addLayout(settings_actions)

    setup_layout.addWidget(QLabel("Layer Suffix"))
    setup_layout.addWidget(suffix_edit)

    action_box = QGroupBox("Run")
    action_layout = QVBoxLayout(action_box)
    frame_scope_row, current_frames_radio, all_frames_radio = (
        create_frame_scope_controls()
    )
    run_button = QPushButton("Run Reconstruction")
    run_button.setToolTip("Requires a loaded scan and a selected, non-edited preset")
    status_label = QLabel("Select a preset and run.")
    action_layout.addWidget(frame_scope_row)
    action_layout.addWidget(run_button)
    action_layout.addWidget(status_label)

    outer.addWidget(source_box)
    outer.addWidget(setup_box)
    outer.addWidget(action_box)
    outer.addStretch()

    return ReconstructionDock(
        widget=widget,
        scan_status_label=scan_status_label,
        preset_combo=preset_combo,
        current_frames_radio=current_frames_radio,
        all_frames_radio=all_frames_radio,
        all_settings_button=all_settings_button,
        settings_edit=settings_edit,
        apply_preset_button=apply_preset_button,
        save_preset_button=save_preset_button,
        remove_preset_button=remove_preset_button,
        speed_of_sound_slider=speed_of_sound_slider,
        speed_of_sound_value_label=speed_of_sound_value_label,
        suffix_edit=suffix_edit,
        run_button=run_button,
        status_label=status_label,
    )
