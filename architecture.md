# PATARI Architecture (simplified and maybe outdated)

```mermaid
classDiagram
class TaskControllerBase {
  #patari_controller
  #viewer
  +bind_events()*
  +unbind_events()*
  +teardown()*
}

class ScanController {
  +load_scan()
  +on_browse_folder_clicked()
  +on_scan_selected()
}

class RoiController {
  +initialize_roi_library()
  +update_live_table()
  +on_shapes_data_changed()
}

class AnalysisController {
  +on_generate_time_analysis_clicked()
  +on_refresh_histograms_clicked()
  +on_refresh_spectrum_clicked()
}

class UnmixingController {
  +initialize_ui()
  +on_run_unmixing_clicked()
}

class SegmentationController {
  +get_segmenter()
  +on_generate_tissue_segmentation_clicked()
}

class PatariController {
  +viewer
  +scan_ctrl
  +roi_ctrl
  +analysis_ctrl
  +unmixing_ctrl
  +segmentation_ctrl
}

class UIManager {
  +setup_docks()
  +connect_events()
}

TaskControllerBase <|-- ScanController
TaskControllerBase <|-- RoiController
TaskControllerBase <|-- AnalysisController
TaskControllerBase <|-- UnmixingController
TaskControllerBase <|-- SegmentationController

PatariController -->ScanController
PatariController -->RoiController
PatariController -->AnalysisController
PatariController -->UnmixingController
PatariController -->SegmentationController

UIManager --> PatariController