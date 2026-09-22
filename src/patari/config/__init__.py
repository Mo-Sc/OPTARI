from patari.config.config import PatariConfig

try:
    settings = PatariConfig.load_from_user_dir()
except Exception as exc:
    raise RuntimeError(
        f"Failed to load PATARI configuration ({exc}). Please ensure your config file is "
        "valid JSON and matches the expected schema."
    ) from exc