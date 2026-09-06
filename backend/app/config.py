from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_timezone: str = "Asia/Jakarta"
    app_base_url: str = "http://localhost"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://fuel_app:change_me@postgres:5432/fuel_intelligence"
    redis_url: str = "redis://redis:6379/0"
    llm_provider: str = "mock"
    llm_api_key: SecretStr | None = None
    geocoding_provider: str = "google"
    google_maps_api_key: SecretStr | None = None
    google_places_timeout_seconds: int = 15
    google_places_max_retry: int = 3
    google_places_request_delay_ms: int = 250
    tbbm_duplicate_radius_meters: int = 300
    tbbm_name_similarity_threshold: float = 0.8
    runtime_secret_dir: str = "/home/app/.config/fuel-intelligence"
    app_encryption_key: SecretStr | None = None
    email_token_encryption_key: SecretStr | None = None
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None
    microsoft_client_id: str | None = None
    microsoft_client_secret: SecretStr | None = None
    microsoft_tenant: str = "common"
    microsoft_oauth_redirect_uri: str | None = None
    notification_retry_delays_seconds: list[int] = [0, 60, 300, 900]
    notification_job_max_attempts: int = 4
    notification_dispatch_seconds: int = 15
    oauth_state_ttl_seconds: int = 600
    test_email_rate_limit_per_minute: int = 5
    tiktok_provider: str = "SCRAPECREATORS"
    scrapecreators_api_key: SecretStr | None = None
    scrapecreators_base_url: str = "https://api.scrapecreators.com"
    scrapecreators_timeout_seconds: int = 30
    whatsapp_provider: str = "mock"
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None
    internal_api_token: SecretStr = SecretStr("change_me")
    alert_recipient: str = "operations-local"
    daily_digest_hour: int = 7
    live_news_enabled: bool = True
    news_fetch_concurrency: int = 12
    news_fetch_timeout_seconds: int = 10
    news_priority_minutes: int = 60
    news_general_minutes: int = 120
    tiktok_due_check_seconds: int = 60
    tiktok_stale_run_minutes: int = 120
    geo_enrichment_minutes: int = 360
    incident_recalc_minutes: int = 30
    risk_recalc_minutes: int = 30
    analytics_refresh_minutes: int = 60
    supply_risk_weights: dict[str, float] = {"severity": 0.50, "sources": 1.0, "velocity": 1.0, "confidence": 1.0, "location": 1.0, "corroboration": 1.0}
    hsse_risk_weights: dict[str, float] = {"severity": 0.42, "consequence": 1.0, "confidence": 1.0, "sources": 0.45, "corroboration": 0.45}

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
