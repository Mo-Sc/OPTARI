"""Viewer export controller."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import cv2
from napari.utils.progress import cancelable_progress
from qtpy.QtWidgets import QFileDialog

from patari.controllers.base import TaskControllerBase
from patari.io.utils import colorbars_visible
from patari.utils.viewer import show_activity_dock
from patari.widgets.viewer_export_dialog import ViewerExportDialog

logger = logging.getLogger(__name__)


class ViewerExportController(TaskControllerBase):
    """Export the currently visible viewer content as image or video."""

    @staticmethod
    def on_export_clicked(controller) -> None:
        viewer = controller.viewer
        parent_widget = viewer.window._qt_window
        active_layer = viewer.layers.selection.active
        n_frames = viewer.dims.nsteps[0] if viewer.dims.ndim > 0 else 1
        dialog = ViewerExportDialog(parent_widget, video_available=n_frames > 1)
        if dialog.exec() != ViewerExportDialog.Accepted:
            return

        dialog_settings = dialog.get_dialog_export_settings()
        default_name = f"PATARIVIEW_{active_layer.name if active_layer else 'viewer'}"
        if not dialog_settings["video"]:
            frame_id = viewer.dims.current_step[0] if viewer.dims.ndim > 0 else 0
            default_name += f"_F{frame_id}"
        channel_id = viewer.dims.current_step[1] if viewer.dims.ndim > 1 else 0
        default_name += f"_C{channel_id}"

        if dialog_settings["video"]:
            ViewerExportController._export_video(viewer, parent_widget, default_name, n_frames, dialog_settings)
            return

        ViewerExportController._export_image(viewer, parent_widget, default_name, dialog_settings["include_colorbars"])

    @staticmethod
    def _export_image(viewer, parent_widget, default_name: str, include_colorbars: bool) -> None:
        filename, file_filter = QFileDialog.getSaveFileName(
            parent_widget,
            "Export Image",
            f"{default_name}.png",
            "PNG Images (*.png);;TIFF Images (*.tiff)",
        )
        if not filename:
            return

        filename = Path(filename).with_suffix(".tiff" if "TIFF" in file_filter else ".png")

        with colorbars_visible(viewer, include_colorbars):
            image = viewer.screenshot(canvas_only=True)[..., :3]
        cv2.imwrite(str(filename), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        logger.info("Exported image to %s", filename)

    @staticmethod
    def _export_video(viewer, parent_widget, default_name: str, n_frames: int, dialog_settings) -> None:
        """Capture the viewer canvas frame by frame and mux it into an MP4.

        Unlike the reconstruction/unmixing/segmentation tasks, this cannot run in a worker
        thread. `camera.mouse_pan`/`mouse_zoom` are blocked to prevent the camera drifting mid-capture 
        since that would corrupt the recording
        """
        filename, _ = QFileDialog.getSaveFileName(
            parent_widget,
            "Export Video",
            f"{default_name}.mp4",
            "MP4 Video (*.mp4)",
        )
        if not filename:
            return

        filename = Path(filename).with_suffix(".mp4")
        # Write to a scratch file and rename only once every frame is captured, so a
        # cancelled or failed export can never leave a corrupt file at the real destination.
        fd, tmp_name = tempfile.mkstemp(dir=filename.parent, prefix=f".{filename.stem}-", suffix=".mp4")
        os.close(fd)
        tmp_path = Path(tmp_name)
        tmp_path.unlink()

        fps = dialog_settings["fps"]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        original_step = viewer.dims.current_step
        mouse_pan, mouse_zoom = viewer.camera.mouse_pan, viewer.camera.mouse_zoom
        writer = None
        frames_written = 0

        try:
            logger.info("Exporting video to %s at %.3f FPS...", filename, fps)
            show_activity_dock(viewer, True)
            viewer.camera.mouse_pan = False
            viewer.camera.mouse_zoom = False
            with colorbars_visible(viewer, dialog_settings["include_colorbars"]):
                for frame_id in cancelable_progress(range(n_frames), desc="Exporting video"):
                    viewer.dims.current_step = (frame_id, *viewer.dims.current_step[1:])
                    frame = viewer.screenshot(canvas_only=True)[..., :3]
                    if writer is None:
                        height, width = frame.shape[:2]
                        writer = cv2.VideoWriter(str(tmp_path), fourcc, fps, (width, height))
                    writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                    frames_written += 1
        finally:
            viewer.dims.current_step = original_step
            viewer.camera.mouse_pan = mouse_pan
            viewer.camera.mouse_zoom = mouse_zoom
            show_activity_dock(viewer, False)
            if writer is not None:
                writer.release()
            if frames_written == n_frames:
                tmp_path.replace(filename)
                logger.info("Video export done: %s", filename)
            else:
                tmp_path.unlink(missing_ok=True)
                logger.info(
                    "Video export cancelled or failed after %s/%s frame(s); discarded",
                    frames_written,
                    n_frames,
                )
