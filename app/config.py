from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    canvas_token: str
    canvas_domain: str
    spreadsheet_id: str
    redis_url: str
    google_creds_json: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# Instantiated at import time — fails fast if any required var is missing.
settings = Settings()
