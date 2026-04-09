"""AI Agent Backend — Configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    primary_model: str = "claude-sonnet-4-20250514"
    fallback_model: str = "gpt-4o-mini"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "agent_memory"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "agent_db"
    postgres_user: str = "agent"
    postgres_password: str = "changeme_in_production"

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_cors_origins: str = "http://localhost:3000"

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "ai-agent"

    # Security
    api_secret_key: str = "changeme_generate_a_random_key"

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_default_voice_id: str = ""

    # S3 / DO Spaces / MinIO
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "agent-content"
    s3_public_url: str = "http://localhost:9000/agent-content"

    # Microsoft Graph / Outlook
    microsoft_tenant_id: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_mailbox: str = ""
    microsoft_graph_base_url: str = "https://graph.microsoft.com/v1.0"

    # TMS integration
    tms_base_url: str = ""
    tms_api_key: str = ""
    tms_timeout_seconds: int = 30

    # Freight workflow defaults
    quote_wait_minutes_default: int = 20
    profit_margin_percent_default: float = 15.0
    profit_margin_floor_default: float = 0.0

    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",")]

    @property
    def microsoft_token_url(self) -> str:
        return (
            "https://login.microsoftonline.com/"
            f"{self.microsoft_tenant_id}/oauth2/v2.0/token"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
