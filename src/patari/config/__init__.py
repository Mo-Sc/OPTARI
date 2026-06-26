from patari.config.config import PatariConfig

try:
    settings = PatariConfig.load_from_user_dir()
except Exception:
    raise RuntimeError("Failed to load PATARI configuration. Please ensure your config file is valid JSON and matches the expected schema.")