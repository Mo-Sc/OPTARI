from __future__ import annotations

from qtpy.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class ViewerExportDialog(QDialog):
    """Dialog for exporting the currently visible viewer content."""

    def __init__(self, parent, video_available: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Export Viewer Content")
        self.setMinimumSize(300, 150)

        self.colorbar_checkbox = QCheckBox("Include colorbars")
        self.colorbar_checkbox.setChecked(True)

        self.video_checkbox = QCheckBox("Video")
        self.video_checkbox.setEnabled(video_available)
        self.video_checkbox.setToolTip(
            "Export all frames as an MP4 instead of a single image "
            "(disabled for single-frame scans)"
        )
        self.video_checkbox.toggled.connect(self._on_video_toggled)

        self.fps_row = QWidget()
        fps_layout = QHBoxLayout(self.fps_row)
        fps_layout.setContentsMargins(0, 0, 0, 0)
        fps_layout.addWidget(QLabel("FPS:"), 0)
        self.fps_spinbox = QDoubleSpinBox()
        self.fps_spinbox.setRange(0.1, 240.0)
        self.fps_spinbox.setDecimals(2)
        fps_layout.addWidget(self.fps_spinbox, 1)

        from optari.config import settings
        self.fps_spinbox.setValue(float(settings.general.DEFAULT_PLAYBACK_FPS))
        self.fps_row.setVisible(False)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addWidget(self.colorbar_checkbox)
        outer.addWidget(self.video_checkbox)
        outer.addWidget(self.fps_row)
        outer.addWidget(buttons)

    def _on_video_toggled(self, checked: bool) -> None:
        self.fps_row.setVisible(checked)

    def get_dialog_export_settings(self) -> dict:
        return {
            "include_colorbars": self.colorbar_checkbox.isChecked(),
            "video": self.video_checkbox.isChecked(),
            "fps": self.fps_spinbox.value(),
        }
