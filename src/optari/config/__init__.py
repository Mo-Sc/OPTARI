from optari.config.config import OptariConfig

try:
    settings = OptariConfig.load_from_user_dir()
except Exception as exc:
    raise RuntimeError(
        f"Failed to load OPTARI configuration ({exc}). Please ensure your config file is "
        "valid JSON and matches the expected schema."
    ) from exc
