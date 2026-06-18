import logging
import shutil
from pathlib import Path
import requests
from typing import Generator


logger = logging.getLogger(__name__)


def get_user_dir() -> Path:
    """sets env var for user home dir and fills it with defaults if it doesn't exist."""

    user_dir = Path.home() / ".patari"
    
    # First-run:
    if not Path.exists(user_dir / "config" / "config.json"):
        # create the user dir and subdirs for config, logs, models
        logger.info(f"Creating user directory at {user_dir}")
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / "config").mkdir(exist_ok=True)
        (user_dir / "logs").mkdir(exist_ok=True)
        (user_dir / "models").mkdir(exist_ok=True)

        # copy default config files from patari/src/patari/data/default_configs
        default_configs_dir = Path(__file__).resolve().parent.parent / "config" / "default_configs"

        if not default_configs_dir.exists():
            raise FileNotFoundError(f"Default configs directory not found at {default_configs_dir}")
        
        for config_file in default_configs_dir.glob("*.json"):
            shutil.copy(config_file, user_dir / "config" / config_file.name)
        logger.info(f"Copied default config files to {user_dir / 'config'}")
                
    return user_dir

def get_user_config_file() -> Path:
    """Returns the path to the configuration file."""
    return get_user_dir() / "config" / "config.json"

def get_user_roi_library_file() -> Path:
    """Returns the path to the ROI library file."""
    return get_user_dir() / "config" / "roi_library.json"

def get_user_log_file() -> Path:
    """Returns the path to the log file."""
    return get_user_dir() / "logs" / "patari.log"

def get_user_models_dir() -> Path:
    """Returns the path to the models directory."""
    return get_user_dir() / "models"

def get_user_seg_models_config_file() -> Path:
    """Returns the path to the segmentation models configuration file."""
    return get_user_dir() / "config" / "segmentation_models.json"

def configure_napari_preferences() -> None:
    """configure PATRI specific napari settings (playback fps, save window state, grid stride)."""
    try:
        import napari
        napari_settings = napari.settings.get_settings()
        
        napari_settings.application.playback_fps = 5
        napari_settings.application.save_window_state = True
        napari_settings.application.grid_stride = -2
        logger.info("PATARI: Clinical environment preferences applied successfully.")
    except Exception as e:
        logger.warning(f"Could not apply Napari preferences: {e}")


def download_file_stream(url: str, dest_path: Path) -> Generator[float, None, None]:
    """
    Downloads a file from a URL to a destination path
    yield  current progress percentage
    """
    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0
    chunk_size = 1024 * 1024

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Temporary file pointer to prevent corrupted partial downloads if aborted
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

    try:
        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        yield progress
                    else:
                        yield -1.0 # Unknown total size fallback

        # Download complete, rename temp file to actual file name
        tmp_path.rename(dest_path)
        logger.info(f"Successfully downloaded {dest_path.name}")
        
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink() # Clean up the broken partial download
        logger.error(f"Failed to download file from {url}: {e}")
        raise e