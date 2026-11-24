import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    model_mode: str
    model_api_key: str | None
    model_base_url: str | None
    model_name: str | None
    chaoxing_enabled: bool = False
    connector_key: str | None = None
    runtime_dir: str | None = None


def load_settings() -> Settings:
    api_key = os.getenv("LEARNFLOW_MODEL_API_KEY") or None
    return Settings(
        model_mode="live" if api_key else "mock",
        model_api_key=api_key,
        model_base_url=os.getenv("LEARNFLOW_MODEL_BASE_URL"),
        model_name=os.getenv("LEARNFLOW_MODEL_NAME"),
        chaoxing_enabled=(
            os.getenv("LEARNFLOW_CHAOXING_ENABLED", "").strip().casefold()
            in {"1", "true", "yes", "on"}
        ),
        connector_key=os.getenv("LEARNFLOW_CONNECTOR_KEY") or None,
        runtime_dir=os.getenv("LEARNFLOW_DATA_DIR"),
    )
