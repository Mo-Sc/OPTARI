"""Dialog asking for a new ROI preset's name, description, location and top margin."""

from __future__ import annotations

from qtpy.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
)


def prompt_roi_preset(
    margins_by_location: dict[str, float], current_location: str
) -> tuple[str, str, str | None, float] | None:
    """Ask for a preset's name, description, optional location and its top margin.

    *margins_by_location* maps each location on offer to the ROI's measured margin
    below that class's top edge, which prefills the margin when it's picked.
    """
    dialog = QDialog()
    dialog.setWindowTitle("Save ROI")

    form = QFormLayout(dialog)
    preset_name_edit = QLineEdit()
    description_edit = QLineEdit()
    location_combo = QComboBox()
    location_combo.addItem("None (static)", userData=None)
    for name in margins_by_location:
        location_combo.addItem(name, userData=name)
    location_combo.setEnabled(bool(margins_by_location))
    location_combo.setToolTip(
        "Segmentation class this preset is placed in, centred horizontally"
        if margins_by_location
        else "Run segmentation first to place this preset by location"
    )
    margin_spin = QDoubleSpinBox()
    margin_spin.setRange(-100.0, 100.0)
    margin_spin.setDecimals(2)
    margin_spin.setSuffix(" mm")
    margin_spin.setToolTip(
        "How far below the location's top edge (at the image centre) the ROI's top "
        "is placed. Prefilled with where the ROI is now"
    )

    def on_location_changed() -> None:
        location = location_combo.currentData()
        margin_spin.setEnabled(location is not None)
        margin_spin.setValue(margins_by_location.get(location, 0.0))

    location_combo.currentIndexChanged.connect(on_location_changed)
    location_combo.setCurrentIndex(
        max(location_combo.findData(current_location), 0)
    )
    on_location_changed()

    form.addRow("ROI Name:", preset_name_edit)
    form.addRow("Description (optional):", description_edit)
    form.addRow("Location:", location_combo)
    form.addRow("Top margin:", margin_spin)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)

    if dialog.exec() != QDialog.Accepted:
        return None

    name = preset_name_edit.text().strip()
    if not name:
        return None
    return (
        name,
        description_edit.text().strip(),
        location_combo.currentData(),
        margin_spin.value() if margin_spin.isEnabled() else 0.0,
    )
