from __future__ import annotations

from typing import TYPE_CHECKING

from patari.widgets.annotation_dock import create_annotation_dock
from patari.widgets.histogram_dock import create_histogram_dock
from patari.widgets.info_dock import create_info_dock
from patari.widgets.reconstruction_dock import create_reconstruction_dock
from patari.widgets.roi_dock import create_roi_dock
from patari.widgets.scan_browser_dock import create_scan_browser_dock
from patari.widgets.segmentation_dock import create_segmentation_dock
from patari.widgets.spectrum_dock import create_spectrum_dock
from patari.widgets.time_analysis_dock import create_time_analysis_dock
from patari.widgets.unmixing_dock import create_unmixing_dock

if TYPE_CHECKING:
    from patari.controllers.patari_controller import PatariController


class UiManager:
    """Build and wire dock widgets for a single PATARI controller instance."""

    @staticmethod
    def setup_docks(controller: "PatariController") -> None:
        # Create docks once per controller instance.
        if controller.scan_browser is None:
            controller.scan_browser = create_scan_browser_dock()
            controller._scan_browser_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.scan_browser.widget,
                    name="Scan Browser",
                    area="right",
                )
            )

        if controller.info is None:
            controller.info = create_info_dock()
            controller.viewer.window.add_dock_widget(
                controller.info.widget,
                name="Active Slice Info",
                area="left",
            )

        if controller.roi is None:
            controller.roi = create_roi_dock()
            controller._roi_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.roi.widget,
                    name="Tabular",
                    area="bottom",
                )
            )

        if controller.time_analysis is None:
            controller.time_analysis = create_time_analysis_dock()
            controller._time_analysis_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.time_analysis.widget,
                    name="Time Analysis",
                    area="bottom",
                )
            )

        if controller.histograms is None:
            controller.histograms = create_histogram_dock()
            controller._histograms_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.histograms.widget,
                    name="Histogram",
                    area="bottom",
                )
            )

        if controller.spectrum is None:
            controller.spectrum = create_spectrum_dock()
            controller._spectrum_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.spectrum.widget,
                    name="Spectrum",
                    area="bottom",
                )
            )

        if controller.annotation is None:
            controller.annotation = create_annotation_dock()
            controller._annotation_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.annotation.widget,
                    name="Annotation",
                    area="right",
                )
            )

        if controller.segmentation is None:
            controller.segmentation = create_segmentation_dock(
                model_options=controller.segmentation_model_options(),
                default_model_id=controller.active_segmentation_model_id,
            )
            controller._segmentation_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.segmentation.widget,
                    name="Segmentation",
                    area="right",
                )
            )
            controller.on_segmentation_model_changed()

        if controller.unmixing is None:
            controller.unmixing = create_unmixing_dock()
            controller._unmixing_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.unmixing.widget,
                    name="Unmixing",
                    area="right",
                )
            )

        # Reconstruction UI is hidden until fully implemented.
        # if controller.reconstruction is None:
        #     controller.reconstruction = create_reconstruction_dock()
        #     controller._reconstruction_dock_widget = (
        #         controller.viewer.window.add_dock_widget(
        #             controller.reconstruction.widget,
        #             name="Reconstruction",
        #             area="right",
        #         )
        #     )

        UiManager._tabify_docks(controller)

    @staticmethod
    def _tabify_docks(controller: "PatariController") -> None:
        qt_window = getattr(controller.viewer.window, "_qt_window", None)
        if qt_window is None:
            return

        # Bottom: ROI, Time Analysis, Histograms, Spectrum
        qt_window.tabifyDockWidget(
            controller._roi_dock_widget,
            controller._time_analysis_dock_widget,
        )
        qt_window.tabifyDockWidget(
            controller._roi_dock_widget,
            controller._histograms_dock_widget,
        )
        qt_window.tabifyDockWidget(
            controller._roi_dock_widget,
            controller._spectrum_dock_widget,
        )

        # Right: Scan Browser + Annotation + Segmentation + Unmixing + Reconstruction
        qt_window.tabifyDockWidget(
            controller._scan_browser_dock_widget,
            controller._annotation_dock_widget,
        )
        qt_window.tabifyDockWidget(
            controller._scan_browser_dock_widget,
            controller._segmentation_dock_widget,
        )
        qt_window.tabifyDockWidget(
            controller._scan_browser_dock_widget,
            controller._unmixing_dock_widget,
        )
        # qt_window.tabifyDockWidget(
        #     controller._scan_browser_dock_widget,
        #     controller._reconstruction_dock_widget,
        # )

    @staticmethod
    def connect_events(controller: "PatariController") -> None:
        controller._connect_shapes_layer_events()

        controller.viewer.dims.events.point.connect(controller.on_dims_changed)

        # close the currently open scan handle when Qt starts shutting down
        # probably not necessary, just for cleanup
        # but might help in the future for multiple viewer windows / sessions in the same process
        from qtpy.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(controller._close_current_scan)

        # TODO: should reordering / adding / removing layers trigger anything?
        # controller.viewer.layers.events.reordered.connect(controller.on_layers_changed)
        # controller.viewer.layers.events.inserted.connect(controller.on_layers_changed)
        # controller.viewer.layers.events.removed.connect(controller.on_layers_changed)
        controller.viewer.layers.selection.events.changed.connect(
            controller.on_selection_changed
        )

        if controller.roi is not None:
            controller.roi.save_button.clicked.connect(
                controller.on_save_clicked
            )
            controller.roi.delete_button.clicked.connect(
                controller.on_delete_saved_clicked
            )
            controller.roi.xlsx_button.clicked.connect(
                controller.on_xlsx_export_clicked
            )

        if controller.time_analysis is not None:
            controller.time_analysis.generate_button.clicked.connect(
                controller.on_generate_time_analysis_clicked
            )

        if controller.histograms is not None:
            controller.histograms.refresh_button.clicked.connect(
                controller.on_refresh_histograms_clicked
            )

        if controller.spectrum is not None:
            controller.spectrum.refresh_button.clicked.connect(
                controller.on_refresh_spectrum_clicked
            )

        if controller.annotation is not None:
            for edit in (
                controller.annotation.roi_clip_min_edit,
                controller.annotation.roi_clip_max_edit,
                controller.annotation.roi_exclude_min_edit,
                controller.annotation.roi_exclude_max_edit,
            ):
                edit.editingFinished.connect(
                    controller._on_roi_intensity_settings_changed
                )
                # required for reset via 'unset' clear button
                edit.textChanged.connect(
                    lambda t, _e=edit: (
                        controller._on_roi_intensity_settings_changed()
                        if (t or "").strip() == ""
                        else None
                    )
                )

            controller.annotation.roi_clipping_box.toggled.connect(
                lambda checked: controller._on_roi_intensity_settings_changed()
            )
            controller.annotation.roi_exclusion_box.toggled.connect(
                lambda checked: controller._on_roi_intensity_settings_changed()
            )

            controller.annotation.roi_library_list.itemClicked.connect(
                lambda item: controller.on_roi_library_item_selected(
                    item.text()
                )
            )
            controller.annotation.roi_library_list.itemDoubleClicked.connect(
                lambda item: controller.on_roi_library_item_clicked(
                    item.text()
                )
            )
            controller.annotation.save_roi_button.clicked.connect(
                controller.on_save_roi_library_clicked
            )
            controller.annotation.remove_roi_button.clicked.connect(
                controller.on_remove_roi_library_clicked
            )
            controller.annotation.save_library_button.clicked.connect(
                controller.on_save_roi_library_file_clicked
            )

        if controller.segmentation is not None:
            controller.segmentation.segmentation_model_combo.currentIndexChanged.connect(
                controller.on_segmentation_model_changed
            )
            controller.segmentation.select_all_classes_button.clicked.connect(
                controller.on_segmentation_select_all_classes_clicked
            )
            controller.segmentation.clear_classes_button.clicked.connect(
                controller.on_segmentation_clear_classes_clicked
            )
            controller.segmentation.generate_tissue_segmentation_button.clicked.connect(
                controller.on_generate_tissue_segmentation_clicked
            )

        if controller.scan_browser is not None:
            controller.scan_browser.browse_button.clicked.connect(
                controller.on_browse_folder_clicked
            )
            controller.scan_browser.scans_list.currentRowChanged.connect(
                controller.on_scan_selected
            )
            controller.scan_browser.hdf5_button.clicked.connect(
                controller.on_hdf5_export_clicked
            )

        if controller.unmixing is not None:
            controller.unmixing.preset_combo.currentIndexChanged.connect(
                controller.on_unmixing_preset_changed
            )
            controller.unmixing.chromophores_list.itemChanged.connect(
                controller.on_unmixing_chromophores_changed
            )
            controller.unmixing.select_all_wavelengths_button.clicked.connect(
                controller.on_unmixing_select_all_wavelengths_clicked
            )
            controller.unmixing.clear_wavelengths_button.clicked.connect(
                controller.on_unmixing_clear_wavelengths_clicked
            )
            controller.unmixing.run_button.clicked.connect(
                controller.on_run_unmixing_clicked
            )
