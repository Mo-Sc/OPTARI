from __future__ import annotations

import numpy as np
from qtpy.QtCore import Qt, QTimer
from qtpy.QtGui import QImage, QPixmap
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from patari.io.rendering import render_layer_to_image

COLORMAPS = [
    "viridis", "plasma", "inferno", "magma", "cividis",
    "hot", "cool", "bone", "gray", "twilight_shifted"
]


class LayerExportDialog(QDialog):
    """Modal dialog for configuring layer export with a live preview."""

    def __init__(self, parent, layer_data: np.ndarray, layer, contrast_limits: tuple[float, float] | None):
        super().__init__(parent)
        self.setWindowTitle("Export Layer")
        self.setMinimumSize(700, 500)

        self.layer_data = layer_data.astype(float)
        flat = self.layer_data.ravel()
        flat = flat[~np.isnan(flat)]
        self.data_min = float(flat.min())
        self.data_max = float(flat.max())

        # Detect default colormap from layer (Shapes layers have no colormap)
        colormap = getattr(layer, "colormap", None)
        self.default_colormap = colormap.name if colormap is not None else "viridis"

        # Contrast init: use provided limits (e.g. from layer.contrast_limits), clamped to data range
        vmin, vmax = (float(contrast_limits[0]), float(contrast_limits[1])) if contrast_limits is not None else (self.data_min, self.data_max)
        vmin = max(self.data_min, min(self.data_max, vmin))
        vmax = max(self.data_min, min(self.data_max, vmax))
        span = self.data_max - self.data_min
        self.init_vmin, self.init_vmax = vmin, vmax
        self.init_vmin_pct = int(round((vmin - self.data_min) / span * 100)) if span > 0 else 0
        self.init_vmax_pct = int(round((vmax - self.data_min) / span * 100)) if span > 0 else 100

        self._preview_timer = QTimer(singleShot=True)
        self._preview_timer.timeout.connect(self._update_preview)

        self._init_ui()
        self._on_settings_changed()

    def _init_ui(self) -> None:
        # Create contrast widgets before connecting signals to avoid cascade during init
        self.vmin_slider = QSlider(Qt.Horizontal, minimum=0, maximum=100)
        self.vmin_spinbox = QDoubleSpinBox()
        self.vmin_spinbox.setRange(self.data_min, self.data_max)
        self.vmax_slider = QSlider(Qt.Horizontal, minimum=0, maximum=100)
        self.vmax_spinbox = QDoubleSpinBox()
        self.vmax_spinbox.setRange(self.data_min, self.data_max)

        self.vmin_slider.setValue(max(0, min(100, self.init_vmin_pct)))
        self.vmax_slider.setValue(max(0, min(100, self.init_vmax_pct)))
        self.vmin_spinbox.setValue(self.init_vmin)
        self.vmax_spinbox.setValue(self.init_vmax)

        self.vmin_slider.valueChanged.connect(self._on_slider_to_input)
        self.vmax_slider.valueChanged.connect(self._on_slider_to_input)
        self.vmin_spinbox.valueChanged.connect(self._on_input_to_slider)
        self.vmax_spinbox.valueChanged.connect(self._on_input_to_slider)

        settings_widget = QWidget()
        form = QFormLayout(settings_widget)

        vmin_row = QWidget()
        vmin_layout = QHBoxLayout(vmin_row)
        vmin_layout.setContentsMargins(0, 0, 0, 0)
        vmin_layout.addWidget(self.vmin_slider, 1)
        vmin_layout.addWidget(self.vmin_spinbox, 0)
        form.addRow("Contrast Min:", vmin_row)

        vmax_row = QWidget()
        vmax_layout = QHBoxLayout(vmax_row)
        vmax_layout.setContentsMargins(0, 0, 0, 0)
        vmax_layout.addWidget(self.vmax_slider, 1)
        vmax_layout.addWidget(self.vmax_spinbox, 0)
        form.addRow("Contrast Max:", vmax_row)

        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems(COLORMAPS)
        self.colormap_combo.setCurrentText(self.default_colormap)
        self.colormap_combo.currentTextChanged.connect(self._on_settings_changed)
        form.addRow("Colormap:", self.colormap_combo)

        self.colorbar_checkbox = QCheckBox("Include colorbar")
        self.colorbar_checkbox.toggled.connect(self._on_settings_changed)
        form.addRow("", self.colorbar_checkbox)

        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.addWidget(QLabel("Preview:"))
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(300, 300)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background-color:#000;")
        preview_layout.addWidget(self.preview_label, 1)

        content_layout = QHBoxLayout()
        content_layout.addWidget(settings_widget, 0)
        content_layout.addWidget(preview_widget, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addLayout(content_layout, 1)
        outer.addWidget(buttons)

    def _on_slider_to_input(self) -> None:
        """Update spinboxes when sliders move."""
        vmin, vmax = self._contrast_limits()
        self.vmin_spinbox.blockSignals(True)
        self.vmax_spinbox.blockSignals(True)
        self.vmin_spinbox.setValue(vmin)
        self.vmax_spinbox.setValue(vmax)
        self.vmin_spinbox.blockSignals(False)
        self.vmax_spinbox.blockSignals(False)
        self._on_settings_changed()
    
    def _on_input_to_slider(self) -> None:
        """Update sliders when spinboxes change."""
        self.vmin_slider.blockSignals(True)
        self.vmax_slider.blockSignals(True)
        
        vmin = self.vmin_spinbox.value()
        vmax = self.vmax_spinbox.value()
        
        span = self.data_max - self.data_min
        if span > 0:
            vmin_pct = int(round((vmin - self.data_min) / span * 100))
            vmax_pct = int(round((vmax - self.data_min) / span * 100))
        else:
            vmin_pct = 0
            vmax_pct = 100
        
        self.vmin_slider.setValue(max(0, min(100, vmin_pct)))
        self.vmax_slider.setValue(max(0, min(100, vmax_pct)))
        
        self.vmin_slider.blockSignals(False)
        self.vmax_slider.blockSignals(False)
        
        self._on_settings_changed()

    def _on_settings_changed(self) -> None:
        self._preview_timer.start(150)

    def _contrast_limits(self) -> tuple[float, float]:
        span = self.data_max - self.data_min
        vmin = self.data_min + self.vmin_slider.value() / 100.0 * span
        vmax = self.data_min + self.vmax_slider.value() / 100.0 * span
        return vmin, vmax

    def _update_preview(self) -> None:
        vmin, vmax = self._contrast_limits()
        try:
            rgb = render_layer_to_image(
                self.layer_data,
                colormap=self.colormap_combo.currentText(),
                vmin=vmin,
                vmax=vmax,
                include_colorbar=self.colorbar_checkbox.isChecked(),
            )
            h, w = rgb.shape[:2]
            qimg = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            self.preview_label.setPixmap(pixmap.scaledToWidth(300, Qt.SmoothTransformation))
        except Exception as e:
            self.preview_label.setText(f"Preview error: {e}")

    def get_export_settings(self) -> dict:
        vmin, vmax = self._contrast_limits()
        return {
            "vmin": vmin,
            "vmax": vmax,
            "colormap": self.colormap_combo.currentText(),
            "include_colorbar": self.colorbar_checkbox.isChecked(),
        }
