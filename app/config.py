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
    # 仅允许本地开发时使用；生产环境必须调用真实模型，避免把演示响应带上线。
    allow_mock_model: bool = True
    # 知识库向量检索：本地可关闭，生产环境通过 Qdrant 持久化分块向量。
    vector_store_enabled: bool = False
    # 向量服务异常时是否允许回退到请求内的旧版检索，仅供本地调试。
    allow_legacy_rag_fallback: bool = True
    vector_store_provider: str = "qdrant"
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
    # 二阶段排序与置信度门控。hybrid 无额外模型依赖；cross_encoder 可按需启用。
    rag_reranker: str = "hybrid"
    rag_reranker_model: str = "BAAI/bge-reranker-base"
    rag_reranker_model_path: str = ""
    rag_reranker_top_n: int = 5
    rag_min_confidence: float = 0.42
    rag_min_top_score: float = 0.45
    rag_min_score_margin: float = 0.02
    # 引用证据必须满足“词法相关”或“强语义相关”之一，避免 Top-K 中最不差的
    # 弱候选仅因相对排序靠前就被展示为引用。
    rag_min_lexical_score: float = 0.12
    rag_semantic_only_score_threshold: float = 0.72
    # Rerank 后的最终引用门禁。0.85 是 precision-first 的生产初始值，
    # 需要随真实标注集持续校准，不能解释成概率。
    rag_citation_confidence_threshold: float = 0.85
    rag_citation_relevance_saturation: float = 0.60
    rag_citation_margin_saturation: float = 0.15
    rag_source_trust_default: float = 0.80
    rag_source_trust_curated: float = 0.95
    rag_hooks: str = "normalize_query,deduplicate,confidence_guard"
    # 微调模型只改变回答行为，不承担实时知识存储；关闭时继续使用主模型。
    rag_fine_tuned_model_enabled: bool = False
    rag_fine_tuned_model: str = ""
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
    rabbitmq_url: str = "amqp://fieldnote:fieldnote@rabbitmq:5672/%2F"
    rabbitmq_document_queue: str = "fieldnote.document.import"
    rabbitmq_document_dlx: str = "fieldnote.document.dlx"
    document_max_attempts: int = 3
    mcp_server_url: str = "http://mcp-tools:8010/mcp"
    mcp_timeout_seconds: float = 12.0
    weather_default_city: str = "上海"

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
        if self.vector_store_provider.lower() not in {"qdrant"}:
            raise ValueError("VECTOR_STORE_PROVIDER 当前仅支持 qdrant")
        if self.rag_reranker.lower() not in {"off", "hybrid", "cross_encoder"}:
            raise ValueError("RAG_RERANKER 必须是 off、hybrid 或 cross_encoder")
        if self.rag_reranker_top_n < 1 or self.rag_candidate_limit < self.rag_reranker_top_n:
            raise ValueError("RAG_CANDIDATE_LIMIT 必须不小于 RAG_RERANKER_TOP_N，且均为正数")
        for name, value in (
            ("RAG_MIN_CONFIDENCE", self.rag_min_confidence),
            ("RAG_MIN_TOP_SCORE", self.rag_min_top_score),
            ("RAG_MIN_SCORE_MARGIN", self.rag_min_score_margin),
            ("RAG_MIN_LEXICAL_SCORE", self.rag_min_lexical_score),
            ("RAG_SEMANTIC_ONLY_SCORE_THRESHOLD", self.rag_semantic_only_score_threshold),
            ("RAG_CITATION_CONFIDENCE_THRESHOLD", self.rag_citation_confidence_threshold),
            ("RAG_CITATION_RELEVANCE_SATURATION", self.rag_citation_relevance_saturation),
            ("RAG_CITATION_MARGIN_SATURATION", self.rag_citation_margin_saturation),
            ("RAG_SOURCE_TRUST_DEFAULT", self.rag_source_trust_default),
            ("RAG_SOURCE_TRUST_CURATED", self.rag_source_trust_curated),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} 必须在 0 到 1 之间")
        if self.rag_citation_relevance_saturation <= 0 or self.rag_citation_margin_saturation <= 0:
            raise ValueError("RAG 引用置信度的饱和参数必须大于 0")
        if self.rag_fine_tuned_model_enabled and not self.rag_fine_tuned_model:
            raise ValueError("启用 RAG 微调模型路由时必须配置 RAG_FINE_TUNED_MODEL")
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
        if self.allow_mock_model:
            raise ValueError("生产环境禁止 ALLOW_MOCK_MODEL")
        if not self.vector_store_enabled:
            raise ValueError("生产环境必须启用持久化向量库 VECTOR_STORE_ENABLED=true")
        if self.allow_legacy_rag_fallback:
            raise ValueError("生产环境禁止请求内旧版 RAG 降级")
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
