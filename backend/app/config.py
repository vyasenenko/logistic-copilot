"""AI Agent Backend — Configuration."""

from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file_for_settings() -> str | None:
    """Inside Docker, Compose injects host .env into the process; skip dotenv to avoid precedence edge cases."""
    if Path("/.dockerenv").exists():
        return None
    return ".env"


_settings_env_kw: dict = {"env_file_encoding": "utf-8", "extra": "ignore"}
_env_path = _env_file_for_settings()
if _env_path:
    _settings_env_kw["env_file"] = _env_path


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o-mini"
    llm_provider_order: str = "deepseek,openai,anthropic"
    llm_temperature: float = 0.1
    llm_primary_max_tokens: int = 8192
    llm_fallback_max_tokens: int = 4096
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
    microsoft_webhook_client_state: str = ""
    microsoft_webhook_public_base_url: str = ""
    microsoft_webhook_change_type: str = "created"
    microsoft_webhook_resource: str = ""
    microsoft_webhook_startup_delay_seconds: int = 8
    microsoft_webhook_renewal_buffer_minutes: int = 120
    microsoft_webhook_expiration_minutes: int = 10080

    # TMS integration
    tms_base_url: str = ""
    tms_api_key: str = ""
    tms_timeout_seconds: int = 30
    tms_retry_attempts: int = 2

    # Freight workflow defaults
    quote_wait_minutes_default: int = 20
    profit_margin_percent_default: float = 15.0
    profit_margin_floor_default: float = 0.0
    status_sla_hours_default: int = 24
    document_booking_policy_default: str = "review_required"
    document_ocr_provider_order: str = "openai,anthropic"
    document_ocr_timeout_seconds: int = 45
    document_min_ocr_confidence: float = 0.55
    document_min_field_confidence: float = 0.6

    @property
    def postgres_url(self) -> str:
        # Quote user/password so @ : / # etc. do not break the URL (asyncpg gaierror on wrong "host")
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        host = self.postgres_host.strip()
        return f"postgresql+asyncpg://{user}:{password}@{host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",")]

    @property
    def microsoft_token_url(self) -> str:
        return (
            "https://login.microsoftonline.com/"
            f"{self.microsoft_tenant_id}/oauth2/v2.0/token"
        )

    @property
    def microsoft_webhook_notification_url(self) -> str:
        base = self.microsoft_webhook_public_base_url.rstrip("/")
        if not base:
            return ""
        return f"{base}/api/freight/outlook/webhook"

    @property
    def microsoft_webhook_effective_client_state(self) -> str:
        return (
            self.microsoft_webhook_client_state
            or self.api_secret_key[:64]
            or "logistic-copilot-outlook-webhook"
        )

    @property
    def microsoft_webhook_effective_resource(self) -> str:
        if self.microsoft_webhook_resource:
            return self.microsoft_webhook_resource
        mailbox = self.microsoft_mailbox.strip()
        return f"users/{mailbox}/mailFolders('Inbox')/messages" if mailbox else ""

    @property
    def configured_llm_provider_order(self) -> list[str]:
        providers = [provider.strip().lower() for provider in self.llm_provider_order.split(",")]
        return [provider for provider in providers if provider in {"deepseek", "openai", "anthropic"}]

    @property
    def effective_anthropic_model(self) -> str:
        return self.anthropic_model or self.primary_model

    @property
    def effective_openai_model(self) -> str:
        return self.openai_model or self.fallback_model

    model_config = SettingsConfigDict(**dict(_settings_env_kw))


settings = Settings()
