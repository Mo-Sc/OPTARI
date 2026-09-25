import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from imageio.v3 import imread

logger = logging.getLogger(__name__)

DEFAULT_CONFIGS_DIR = Path(__file__).resolve().parent.parent / "config" / "default_configs"

# Names this session's log and ROI table backup. Start time plus process id, so OPTARI instances
# running side by side never write to the same file, and a session's log and backup match.
SESSION_ID = f"{datetime.now():%Y%m%dT%H%M%S}_{os.getpid()}"
KEPT_SESSION_FILES = 20


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
    """The user directory, ``OPTARI_USER_DIR`` or ``~/.optari``, seeded with defaults on first use."""

    user_dir = Path(os.environ.get("OPTARI_USER_DIR", Path.home() / ".optari"))

    config_dir = user_dir / "config"
    if not DEFAULT_CONFIGS_DIR.exists():
        raise FileNotFoundError(f"Default configs directory not found at {DEFAULT_CONFIGS_DIR}")

    # First-run:
    if not (config_dir / "config.json").exists():
        # create the user dir and subdirs for config, logs, models
        print(f"creating OPTARI user directory at {user_dir}")
        user_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(exist_ok=True)
        (user_dir / "logs").mkdir(exist_ok=True)
        (user_dir / "models").mkdir(exist_ok=True)

        for config_file in DEFAULT_CONFIGS_DIR.glob("*.json"):
            shutil.copy2(config_file, config_dir / config_file.name)

        print(f"copied default config files to {config_dir}")

    _copy_default_presets(DEFAULT_CONFIGS_DIR, config_dir)

    return user_dir


def archive_config_dir(config_dir: Path) -> Path:
    """Move an outdated config folder aside; models and logs next to it stay in place."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = config_dir.with_name(f"{config_dir.name}_old_{timestamp}")
    config_dir.rename(archive_dir)
    print(f"archived outdated OPTARI config to {archive_dir}")
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


def get_user_batch_presets_dir() -> Path:
    """Returns the path to the user-editable batch plan presets directory."""
    return get_user_dir() / "config" / "presets" / "batch"


def get_user_segmentation_presets_dir() -> Path:
    """Returns the path to the user-editable segmentation presets directory."""
    return get_user_dir() / "config" / "presets" / "segmentation"


def get_user_config_file() -> Path:
    """Returns the path to the configuration file."""
    return get_user_dir() / "config" / "config.json"

def get_user_autosave_dir() -> Path:
    """Returns the directory holding one Saved Analysis table backup per session."""
    return get_user_dir() / "autosave"

def get_user_logs_dir() -> Path:
    """Returns the directory holding one log file per session."""
    return get_user_dir() / "logs"

def get_user_models_dir() -> Path:
    """Returns the path to the models directory."""
    return get_user_dir() / "models"

def get_user_seg_models_config_file() -> Path:
    """Returns the path to the segmentation models configuration file."""
    return get_user_dir() / "config" / "segmentation_models.json"

def new_session_file(directory: Path, prefix: str, suffix: str) -> Path:
    """This session's file in *directory*, after deleting all but the newest older ones.

    Timestamped names sort chronologically. Room is kept for the new file, so the directory
    holds at most ``KEPT_SESSION_FILES`` files with this prefix.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for old_file in sorted(directory.glob(f"{prefix}_*{suffix}"))[: -(KEPT_SESSION_FILES - 1)]:
        old_file.unlink()
    return directory / f"{prefix}_{SESSION_ID}{suffix}"

def get_default_config_file() -> Path:
    """Returns the path to the packaged default configuration file."""
    return DEFAULT_CONFIGS_DIR / "config.json"

def configure_napari(viewer) -> None:
    """
    configure OPTARI specific napari settings (playback fps, save window state, grid stride).
    Deactivate keyboard search in layers panel to avoid accidental layer selection during ROI drawing.
    """
    # imported here: optari.config imports this module, and headless users of it shouldn't load napari
    from napari.settings import get_settings
    from optari.config import settings

    napari_settings = get_settings()
    napari_settings.application.playback_fps = settings.general.DEFAULT_PLAYBACK_FPS
    napari_settings.application.save_window_state = True
    # one layer per grid cell, in layer list order.
    napari_settings.application.grid_stride = -1
    napari_settings.appearance.theme = "dark"

    # deactivate keyboard search in layers panel because it slows down keyboard-based ROI drawing
    # workaround described here: https://github.com/napari/napari/issues/7551
    # private _qt_viewer (public qt_viewer is deprecated), still present in napari 0.9.1
    viewer.window._qt_viewer.layers.keyboardSearch = lambda s: None

    logger.info("napari preferences applied")


def load_startup_logo(viewer):
    logo_path = Path(__file__).resolve().parent.parent / "config/startup.png"
    if logo_path.exists():
        viewer.add_image(
            imread(logo_path),
            name="Welcome to OPTARI!",
            metadata={"type": "startup_logo"},
        )
