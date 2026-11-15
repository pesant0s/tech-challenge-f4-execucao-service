from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]
    LOG_FORMAT: str = "console"
    LOG_LEVEL: str = "INFO"
    # Atrás do API Gateway o Swagger sai em /execucao/docs, para não colidir com o do OS Service.
    PREFIXO_DOCS: str = ""
    # Sem RABBITMQ_URL a mensageria não sobe: a API atende e os eventos ficam parados no outbox.
    RABBITMQ_URL: str | None = None


settings = Settings()
