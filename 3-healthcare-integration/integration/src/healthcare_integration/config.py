"""All runtime configuration comes from the environment (docker-compose injects it)."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    orthanc_url: str = "http://localhost:8042"
    orthanc_deid_url: str = "http://localhost:8043"
    orthanc_user: str = "orthanc"
    orthanc_password: str = "orthanc"

    ehrbase_url: str = "http://localhost:8080/ehrbase/rest/openehr/v1"
    ehrbase_user: str = "ehrbase-user"
    ehrbase_password: str = "ehrbase"

    deid_secret: str = Field(..., min_length=32, description="hex HMAC key; never default this")
    deid_vault_path: str = "./reident.sqlite"
    deid_namespace: str = "imaging-research"
    deid_max_shift_days: int = 365

    openehr_template_id: str = "imaging_study_summary"
    templates_dir: str = "./templates"
    poll_interval_sec: int = 15

    model_config = {"env_prefix": "", "case_sensitive": False}


def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
