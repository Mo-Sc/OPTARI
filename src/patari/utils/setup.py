import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
import warnings

from imageio.v3 import imread

logger = logging.getLogger(__name__)


def _copy_default_presets(default_configs_dir: Path, user_config_dir: Path) -> None:
    default_presets_dir = default_configs_dir / "presets"
    if not default_presets_dir.exists():
        return

    user_presets_dir = user_config_dir / "presets"
    for preset_file in default_presets_dir.rglob("*.json"):
        target = user_presets_dir / preset_file.relative_to(default_presets_dir)
        # Never overwrite a preset that the user has edited.
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(preset_file, target)


def get_user_dir() -> Path:
    """sets env var for user home dir and fills it with defaults if it doesn't exist."""

    user_dir = Path.home() / ".patari"
    
    config_dir = user_dir / "config"
    default_configs_dir = Path(__file__).resolve().parent.parent / "config" / "default_configs"
    if not default_configs_dir.exists():
        raise FileNotFoundError(f"Default configs directory not found at {default_configs_dir}")

    # First-run:
    if not (config_dir / "config.json").exists():
        # create the user dir and subdirs for config, logs, models
        print(f"Creating user directory at {user_dir}")
        user_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(exist_ok=True)
        (user_dir / "logs").mkdir(exist_ok=True)
        (user_dir / "models").mkdir(exist_ok=True)

        for config_file in default_configs_dir.glob("*.json"):
            shutil.copy2(config_file, config_dir / config_file.name)

        print(f"Copied default config files to {config_dir}")

    _copy_default_presets(default_configs_dir, config_dir)

    return user_dir


def archive_user_dir(user_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = user_dir.with_name(f"{user_dir.name}_old_{timestamp}")
    user_dir.rename(archive_dir)
    print(f"Archived PATARI user directory to {archive_dir}")
    return archive_dir


def get_user_unmixing_presets_dir() -> Path:
    """Returns the path to the user-editable unmixing presets directory."""
    return get_user_dir() / "config" / "presets" / "unmixing"


def get_user_reconstruction_presets_dir() -> Path:
    """Returns the path to the user-editable reconstruction presets directory."""
    return get_user_dir() / "config" / "presets" / "reconstruction"


def get_user_roi_presets_dir() -> Path:
    """Returns the path to the user-editable ROI presets directory."""
    return get_user_dir() / "config" / "presets" / "roi"


def get_user_segmentation_presets_dir() -> Path:
    """Returns the path to the user-editable segmentation presets directory."""
    return get_user_dir() / "config" / "presets" / "segmentation"


def get_user_config_file() -> Path:
    """Returns the path to the configuration file."""
    return get_user_dir() / "config" / "config.json"

def get_user_log_file() -> Path:
    """Returns the path to the log file."""
    return get_user_dir() / "logs" / "patari.log"

def get_user_models_dir() -> Path:
    """Returns the path to the models directory."""
    return get_user_dir() / "models"

def get_user_seg_models_config_file() -> Path:
    """Returns the path to the segmentation models configuration file."""
    return get_user_dir() / "config" / "segmentation_models.json"

def configure_napari(viewer) -> None:
    """
    configure PATRI specific napari settings (playback fps, save window state, grid stride).
    Deactivate keyboard search in layers panel to avoid accidental layer selection during ROI drawing.
    """
    try:
        import napari
        from patari.config import settings
        
        napari_settings = napari.settings.get_settings()
        
        napari_settings.application.playback_fps = settings.general.DEFAULT_PLAYBACK_FPS
        napari_settings.application.save_window_state = True
        napari_settings.application.grid_stride = -2
        napari_settings.appearance.theme = "dark"

        # deactivate keyboard search in layers panel because it slows done keyboard-based ROI drawing
        # workaround described here: https://github.com/napari/napari/issues/7551
        # but gets deprecation warning, so suppress it for now
        # TODO: check how to handle in future versions (still works in 0.80)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            viewer.window.qt_viewer.layers.keyboardSearch = lambda s: None


        logger.info("PATARI: Clinical environment preferences applied successfully.")
    except Exception as e:
        logger.warning(f"Could not apply Napari preferences: {e}")


def load_startup_logo(viewer):
    logo_path = Path(__file__).resolve().parent.parent / "config/startup.png"
    if logo_path.exists():
        viewer.add_image(
            imread(logo_path),
            name="Welcome to PATARI!",
            metadata={"type": "startup_logo"},
        )
