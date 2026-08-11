"""应用配置模块。

所有可随环境变化的参数都集中在这里，并通过 Pydantic Settings 从 ``.env``
读取。业务模块只依赖 ``Settings``，不直接散落读取环境变量，便于测试、部署和
切换模型/数据库/对象存储供应商。
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """经过类型校验的运行时配置；字段名会自动映射为同名大写环境变量。"""

    # 应用与鉴权配置。
    app_name: str = "AI Agent Demo"
    app_env: str = "local"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 120
    cors_allowed_origins: str = ""
    database_url: str = "sqlite:///./ai_agent_demo.db"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1_800
    # 模型配置：项目通过 Anthropic Messages 兼容协议调用服务，base_url 可替换供应商。
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
    # 知识库向量检索：本地可关闭，生产环境通过 Qdrant 持久化分块向量。
    vector_store_enabled: bool = False
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "note_chunks"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_cache_dir: str = ".cache/fastembed"
    embedding_local_files_only: bool = False
    embedding_model_path: str = ""
    vector_request_timeout_seconds: float = 10.0
    rag_top_k: int = 5
    rag_candidate_limit: int = 12
    rag_vector_score_threshold: float = 0.55
    rate_limit_enabled: bool = True
    metrics_enabled: bool = True
    # OSS 配置：长期密钥仅由后端读取，浏览器只接触短期签名 URL。
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_endpoint: str = "https://oss-cn-beijing.aliyuncs.com"
    oss_bucket: str = ""
    oss_object_prefix: str = "ai-agent-demo"
    oss_signed_url_expire_seconds: int = 3_600
    attachment_storage_backend: str = "auto"
    local_upload_dir: str = "/data/uploads"
    local_upload_url_prefix: str = "/api/uploads/local"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        """生产环境启用更严格的启动检查。"""
        return self.app_env.lower() in {"production", "prod"}

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """尽早拒绝危险的生产默认值，避免服务带着弱配置启动。"""
        if not self.is_production:
            return self
        unsafe_secret_keys = {
            "change-me-in-production",
            "replace-with-at-least-32-random-characters",
        }
        if self.secret_key in unsafe_secret_keys or len(self.secret_key) < 32:
            raise ValueError("生产环境 SECRET_KEY 必须是至少 32 位的随机字符串")
        if self.database_url.startswith("sqlite"):
            raise ValueError("生产环境必须使用 MySQL 等独立数据库，不能使用 SQLite")
        if not self.anthropic_auth_token:
            raise ValueError("生产环境必须配置 ANTHROPIC_AUTH_TOKEN")
        if self.vector_store_enabled and not self.qdrant_url:
            raise ValueError("启用向量检索时必须配置 QDRANT_URL")
        if self.vector_store_enabled and not self.qdrant_api_key:
            raise ValueError("生产环境启用向量检索时必须配置 QDRANT_API_KEY")
        if "*" in self.cors_origins:
            raise ValueError("生产环境 CORS_ALLOWED_ORIGINS 禁止使用通配符 *")
        return self


@lru_cache
def get_settings() -> Settings:
    """创建并缓存配置，避免每次请求都重复读取和解析 ``.env``。"""
    return Settings()
