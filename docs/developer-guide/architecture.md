# Architecture

OPTARI is a standalone desktop application, not a napari plugin. `launcher.main()` creates its
own `napari.Viewer` and wraps it in one `OptariController`. It follows a loose
Model-View-Controller split across four layers.

## Layers

- **UI layer** (`widgets/`): dock widgets built by `create_*_dock()` factories. A dock is a
  dataclass of Qt widget references and holds no logic.
- **Control layer** (`controllers/`): one controller per feature area, all owned by
  `OptariController`.
- **Utilities** (`utils/`): config, logging, presets, motion scoring, stateless helpers used by
  controllers.
- **External layer**: PATATO (I/O, reconstruction, unmixing), napari (viewer/layers), ONNX
  Runtime (segmentation, DeepMB), PACFISH (IPASC). See
  [Data & Integrations](data-and-integrations.md) for the PATATO/IPASC boundary.

## `OptariController`

- Session hub, holds the napari `Viewer`, the open `pa_data` (PATATO `PAData`), the active
  image layers, and one instance of each task controller.
- Controllers hold no references to each other. A controller reaches another only through
  `self.optari_controller.<name>_ctrl`, and shared state (`active_recon_layer`,
  `active_us_layer`, `derived_patato_objects`, ...) lives on `OptariController` itself.
- `UiManager` builds the docks and wires every Qt signal to a controller method.
  `MenuManager` builds the menu bar and the Settings/Batch dialogs. `ShortcutManager` binds
  keyboard shortcuts.

## Background work and Batch Mode

- Reconstruction, unmixing and segmentation each expose `prepare(params) -> BackgroundStep` and
  `publish(result, params)`, run on a single shared background-task slot
  (`utils/tasks.py`) so the UI stays responsive and only one heavy operation runs at a time.
- Batch mode (`batch/`) builds the same `params` objects from a preset instead of dock widgets and uses the same `prepare`/`publish`.

## Configuration

- `config/config.py` defines a `OptariConfig`, loaded once from
  `~/.optari/config/config.json` into the module-level `optari.config.settings`.
- Reconstruction/unmixing/segmentation/ROI/batch presets are separate JSON files under
  `~/.optari/config/presets/`, shipped with defaults and user-editable. See
  [Presets](../configuration/presets.md).
- A schema-version mismatch archives `~/.optari/config/` and loads a new default one.

## Deployment

- Packaged as a standalone executable via PyApp. First launch creates `~/.optari` from the
  packaged defaults (`utils/setup.get_user_dir()`).
- PATATO is installed from a custom fork as prebuilt, OS-specific wheels pinned by URL in
  `pyproject.toml`, not from PyPI.
