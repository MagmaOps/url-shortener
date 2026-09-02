from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    base_url: str
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=None)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Raises ``pydantic_settings.ValidationError`` at first call when
    DATABASE_URL or BASE_URL are not present in the environment or .env file.
    """
    return Settings()
