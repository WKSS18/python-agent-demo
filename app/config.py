from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Agent Demo"
    app_env: str = "local"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 120
    database_url: str = "sqlite:///./ai_agent_demo.db"
    # 项目通过 Anthropic 兼容协议调用模型，base_url 可以指向兼容服务商。
    anthropic_auth_token: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-sonnet-4-5"
    # 可单独指定视觉模型；留空时复用 anthropic_model。
    anthropic_vision_model: str = ""
    anthropic_vision_enabled: bool = True
    anthropic_default_opus_model: str = ""
    anthropic_default_sonnet_model: str = ""
    anthropic_default_haiku_model: str = ""
    claude_code_subagent_model: str = ""
    api_timeout_ms: int = 600_000
    # OSS 密钥仅由后端读取，浏览器只接触短期签名 URL。
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_endpoint: str = "https://oss-cn-beijing.aliyuncs.com"
    oss_bucket: str = ""
    oss_object_prefix: str = "ai-agent-demo"
    oss_signed_url_expire_seconds: int = 3_600

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
