from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "SpendWise API"
    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+asyncpg://spendwise:spendwise@db:5432/spendwise"

    KEYCLOAK_ISSUER: str = "http://localhost:8080/realms/spendwise"
    KEYCLOAK_JWKS_URL: str = (
        "http://keycloak:8080/realms/spendwise/protocol/openid-connect/certs"
    )
    KEYCLOAK_AUDIENCE: str = "spendwise-api"

    FRANKFURTER_BASE_URL: str = "https://api.frankfurter.dev"
    EXTERNAL_API_TIMEOUT_SECONDS: float = 5.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
