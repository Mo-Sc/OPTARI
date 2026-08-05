"""Layer export controller."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import cv2
from napari.layers import Image, Shapes
from qtpy.QtWidgets import QFileDialog

from patari.controllers.base import TaskControllerBase
from patari.io.rendering import render_layer_to_image
from patari.widgets.layer_export_dialog import LayerExportDialog

logger = logging.getLogger(__name__)


class LayerExportController(TaskControllerBase):
    """Handle layer export to PNG/TIFF with configurable rendering."""

    @staticmethod
    def _slice_image_data(layer_data: np.ndarray, current_step: tuple[int, ...]) -> np.ndarray:
        if layer_data.ndim <= 2:
            return layer_data

        idx = tuple(
            min(int(current_step[i]), layer_data.shape[i] - 1)
            for i in range(layer_data.ndim - 2)
        )
        return layer_data[idx]

    @staticmethod
    def _iter_image_frames(layer_data: np.ndarray, current_step: tuple[int, ...]):
        if layer_data.ndim <= 2:
            yield layer_data
            return

        non_spatial_shape = layer_data.shape[:-2]
        idx = [min(int(current_step[i]), non_spatial_shape[i] - 1) for i in range(len(non_spatial_shape))]
        for frame_idx in range(non_spatial_shape[0]):
            idx[0] = frame_idx
            yield layer_data[tuple(idx)]

    @staticmethod
    def _roi_vertices_to_pixels(active_layer, us_layer) -> list[np.ndarray]:
        translate_yx = us_layer.translate[-2:]
        scale_yx = us_layer.scale[-2:]
        return [
            (np.asarray(shape, dtype=float)[..., -2:] - translate_yx) / scale_yx
            for shape in active_layer.data
        ]

    @staticmethod
    def _roi_contours_to_mask(roi_vertices: list[np.ndarray], roi_shape_types: list[str], labels_shape: tuple[int, int], line_thickness: int = 1) -> np.ndarray:
        """Draw ROI contours (not filled) onto a mask.
        
        Handles different shape types appropriately:
        - ellipse: drawn as smooth ellipse using cv2.ellipse
        - other: drawn as polylines
        """
        mask = np.zeros(labels_shape, dtype=np.float32)
        for shape_id, (vertices, stype) in enumerate(zip(roi_vertices, roi_shape_types), start=1):
            pts = np.round(vertices).astype(np.int32)
            
            if stype == 'ellipse':
                # Ellipse: bounding box is given as 4 corner points
                # Extract center and axes from bounding box
                bbox = np.array([pts[:, 0], pts[:, 1]])
                center_y = (bbox[0].min() + bbox[0].max()) / 2.0
                center_x = (bbox[1].min() + bbox[1].max()) / 2.0
                axes_y = (bbox[0].max() - bbox[0].min()) / 2.0
                axes_x = (bbox[1].max() - bbox[1].min()) / 2.0
                
                # cv2.ellipse expects (center_x, center_y), (axis_x, axis_y), angle, startAngle, endAngle
                cv2.ellipse(
                    mask,
                    center=(int(center_x), int(center_y)),
                    axes=(int(axes_x), int(axes_y)),
                    angle=0,
                    startAngle=0,
                    endAngle=360,
                    color=float(shape_id),
                    thickness=line_thickness,
                )
            else:
                # Polygon or other: draw as polylines
                # Swap y,x to x,y for OpenCV
                pts_xy = np.stack([pts[:, 1], pts[:, 0]], axis=1)
                cv2.polylines(mask, [pts_xy], isClosed=True, color=float(shape_id), thickness=line_thickness)
        return mask

    @staticmethod
    def on_export_layer_clicked(controller) -> None:
        """Show export dialog for active layer."""
        active_layer = controller.viewer.layers.selection.active
        if active_layer is None:
            logger.warning("No active layer selected")
            return

        parent_widget = controller.viewer.window._qt_window
        current_step = controller.viewer.dims.current_step

        if isinstance(active_layer, Image):
            layer_data = LayerExportController._slice_image_data(active_layer.data, current_step)
            contrast_limits = tuple(active_layer.contrast_limits)
        elif isinstance(active_layer, Shapes):
            us_layer = controller.active_us_layer
            if us_layer is None:
                logger.warning("No ultrasound layer available for ROI export")
                return

            labels_shape = us_layer.data.shape[-2:]
            roi_vertices = LayerExportController._roi_vertices_to_pixels(active_layer, us_layer)
            layer_data = LayerExportController._roi_contours_to_mask(roi_vertices, list(active_layer.shape_type), labels_shape)
            contrast_limits = None
        else:
            logger.warning("Layer type not supported for export: %s", type(active_layer).__name__)
            return

        dialog = LayerExportDialog(parent_widget, layer_data, active_layer, contrast_limits)
        if dialog.exec() != LayerExportDialog.Accepted:
            return

        settings = dialog.get_export_settings()

        default_name = f"{active_layer.name}_export"
        data_min, data_max = float(np.nanmin(layer_data)), float(np.nanmax(layer_data))
        if not (np.isclose(settings["vmin"], data_min) and np.isclose(settings["vmax"], data_max)):
            default_name += f"_{settings['vmin']:.4g}_{settings['vmax']:.4g}"

        is_video = settings["video"] and isinstance(active_layer, Image)
        if settings["video"] and not isinstance(active_layer, Image):
            logger.warning("Video export is only supported for Image layers")
            return

        filename, file_filter = QFileDialog.getSaveFileName(
            parent_widget,
            "Export Layer as Video" if is_video else "Export Layer as Image",
            f"{default_name}.mp4" if is_video else f"{default_name}.png",
            "MP4 Video (*.mp4);;AVI Video (*.avi)" if is_video else "PNG Images (*.png);;TIFF Images (*.tiff *.tif)",
        )
        if not filename:
            return

        filename = Path(filename)
        if is_video:
            if filename.suffix.lower() not in {".mp4", ".avi"}:
                filename = filename.with_suffix(".avi" if "AVI" in file_filter else ".mp4")

            fps = settings["fps"]
            frames = LayerExportController._iter_image_frames(active_layer.data, current_step)
            first_frame_data = next(frames)
            first_rgb = render_layer_to_image(
                first_frame_data,
                colormap=settings["colormap"],
                vmin=settings["vmin"],
                vmax=settings["vmax"],
                include_colorbar=settings["include_colorbar"],
                transparent_background=False,
            )
            height, width = first_rgb.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*("mp4v" if filename.suffix.lower() == ".mp4" else "XVID"))
            writer = cv2.VideoWriter(str(filename), fourcc, fps, (width, height))
            writer.write(cv2.cvtColor(first_rgb, cv2.COLOR_RGB2BGR))

            for frame_data in frames:
                frame_rgb = render_layer_to_image(
                    frame_data,
                    colormap=settings["colormap"],
                    vmin=settings["vmin"],
                    vmax=settings["vmax"],
                    include_colorbar=settings["include_colorbar"],
                    transparent_background=False,
                )
                writer.write(cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))

            writer.release()
            logger.info("Exported video to %s at %.3f FPS", filename, fps)
            return

        if filename.suffix.lower() not in {".png", ".tiff", ".tif"}:
            filename = filename.with_suffix(".tiff" if "TIFF" in file_filter else ".png")

        rgb = render_layer_to_image(
            layer_data,
            colormap=settings["colormap"],
            vmin=settings["vmin"],
            vmax=settings["vmax"],
            include_colorbar=settings["include_colorbar"],
            transparent_background=isinstance(active_layer, Shapes),
        )

        # cv2 expects BGR(A) order
        color_conversion = cv2.COLOR_RGBA2BGRA if rgb.shape[2] == 4 else cv2.COLOR_RGB2BGR
        cv2.imwrite(str(filename), cv2.cvtColor(rgb, color_conversion))
        logger.info("Exported layer to %s", filename)
