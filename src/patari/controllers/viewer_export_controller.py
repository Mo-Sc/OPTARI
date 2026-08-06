"""Viewer export controller."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
from napari.utils.progress import progress
from qtpy.QtWidgets import QFileDialog

from patari.controllers.base import TaskControllerBase
from patari.io.utils import add_colorbars_to_image, pad_image
from patari.widgets.viewer_export_dialog import ViewerExportDialog

from patari.config import settings

logger = logging.getLogger(__name__)


class ViewerExportController(TaskControllerBase):
    """Export the currently visible viewer content as image or video."""

    @staticmethod
    def on_export_clicked(controller) -> None:
        viewer = controller.viewer
        parent_widget = viewer.window._qt_window
        active_layer = viewer.layers.selection.active
        qt_window = viewer.window._qt_window
        n_frames = viewer.dims.nsteps[0] if viewer.dims.ndim > 0 else 1
        dialog = ViewerExportDialog(parent_widget, video_available=n_frames > 1)
        if dialog.exec() != ViewerExportDialog.Accepted:
            return

        dialog_settings = dialog.get_dialog_export_settings()
        is_video = dialog_settings["video"]
        include_colorbars = dialog_settings["include_colorbars"]

        default_name = f"PATARIVIEW_{active_layer.name if active_layer else 'viewer'}"
        if not is_video:
            frame_id = viewer.dims.current_step[0] if viewer.dims.ndim > 0 else 0
            default_name += f"_F{frame_id}"
        channel_id = viewer.dims.current_step[1] if viewer.dims.ndim > 1 else 0
        default_name += f"_C{channel_id}"

        if is_video:
            filename, _ = QFileDialog.getSaveFileName(
                parent_widget,
                "Export Video",
                f"{default_name}.mp4",
                "MP4 Video (*.mp4)",
            )
            if not filename:
                return

            filename = Path(filename).with_suffix(".mp4")
            fps = dialog_settings["fps"]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            original_step = viewer.dims.current_step
            writer = None

            try:
                logger.info("Exporting video to %s at %.3f FPS...", filename, fps)
                # deprecated private API access, however currently only way to force the activity dock to open
                # https://github.com/napari/napari/issues/4598
                viewer.window._status_bar._toggle_activity_dock(True)
                # disable the main window to prevent user interaction during export
                qt_window.setEnabled(False)
                for t in progress(range(n_frames), desc="Exporting video"):
                    viewer.dims.current_step = (t, *viewer.dims.current_step[1:])
                    frame = viewer.screenshot(canvas_only=True)[..., :3]
                    if include_colorbars:
                        frame = add_colorbars_to_image(frame, viewer, bar_width=settings.export.cbar_width, font_size=settings.export.font_size)
                    frame = pad_image(frame, padding=settings.export.padding)
                    if writer is None:
                        height, width = frame.shape[:2]
                        writer = cv2.VideoWriter(str(filename), fourcc, fps, (width, height))
                    writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            finally:
                viewer.dims.current_step = original_step
                if writer is not None:
                    writer.release()
                viewer.window._status_bar._toggle_activity_dock(False)
                qt_window.setEnabled(True) # re-enable the main window after export


            logger.info("Video export done.")
            return

        filename, file_filter = QFileDialog.getSaveFileName(
            parent_widget,
            "Export Image",
            f"{default_name}.png",
            "PNG Images (*.png);;TIFF Images (*.tiff)",
        )
        if not filename:
            return

        filename = Path(filename).with_suffix(".tiff" if "TIFF" in file_filter else ".png")

        image = viewer.screenshot(canvas_only=True)[..., :3]
        if include_colorbars:
            image = add_colorbars_to_image(image, viewer, bar_width=settings.export.cbar_width, font_size=settings.export.font_size)
        image = pad_image(image, padding=settings.export.padding)
        cv2.imwrite(str(filename), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        logger.info("Exported image to %s", filename)
