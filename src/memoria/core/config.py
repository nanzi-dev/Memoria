"""
应用全局配置。所有配置项通过环境变量 / .env 文件注入，
方便在不同模型供应商之间切换，无需改代码。
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Configs(BaseSettings):
    """
    全局配置类，包含所有应用需要的配置项。
    """

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore")
    
    # LLM 配置
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: SecretStr = ""
    llm_model: str = "deepseek-chat"
    llm_light_model: str = ""
    llm_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    llm_light_timeout_seconds: float = Field(default=12.0, gt=0, le=300)
    light_task_max_output_tokens: int = Field(default=400, ge=1, le=4096)
    
    # 轻量任务专用 LLM 配置（可选，留空则使用主 LLM）
    llm_light_base_url: str = ""
    llm_light_api_key: SecretStr = ""

    # Speech 配置（与角色对话模型独立）
    # speech_provider / speech_api_key / speech_base_url / speech_timeout_seconds
    # remain as a deprecated compatibility fallback for pre-split deployments.
    speech_provider: Literal["openai", "openai_compatible", "mimo", "minimax"] = "openai"
    speech_api_key: SecretStr = ""
    speech_base_url: str = "https://api.openai.com/v1"

    # TTS defaults to MiniMax. MiniMax HTTP streaming requires MP3 output.
    speech_tts_provider: Literal["minimax", "openai", "openai_compatible"] = "minimax"
    speech_tts_api_key: SecretStr = ""
    speech_tts_base_url: str = "https://api.minimax.io/v1"
    speech_tts_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    speech_tts_max_retries: int = Field(default=1, ge=0, le=3)
    speech_tts_default_voice: str = "female-shaonv"
    speech_tts_builtin_voices: str = (
        "male-qn-qingse,male-qn-jingying,male-qn-badao,"
        "male-qn-daxuesheng,female-shaonv,female-yujie,"
        "female-chengshu,female-tianmei"
    )

    # STT uses a separate OpenAI-compatible endpoint by default.
    speech_stt_provider: Literal["openai", "openai_compatible"] = "openai_compatible"
    speech_stt_api_key: SecretStr = ""
    speech_stt_base_url: str = "https://api.openai.com/v1"
    speech_stt_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    speech_stt_max_retries: int = Field(default=1, ge=0, le=3)
    speech_stt_model: str = "gpt-4o-mini-transcribe"
    speech_tts_model: str = "speech-2.8-turbo"
    speech_output_format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "mp3"
    speech_storage_path: str = "./data/speech"
    speech_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    speech_stt_upload_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    speech_custom_voice_upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    speech_cache_max_age_seconds: int = Field(default=7 * 24 * 60 * 60, ge=0)
    speech_cache_max_bytes: int = Field(default=512 * 1024 * 1024, ge=0)
    
    # 应用配置
    # development | production。production 下强制 Secure Cookie，并关闭进程内 token 回退。
    memoria_env: Literal["development", "production"] = "development"
    database_path: str = "./data/sqlite_db/memoria.db"
    database_url: str = ""
    auth_cookie_secure: bool = False
    admin_bootstrap_token: SecretStr = ""
    # 进程内写操作限流（多进程/多实例下各自独立，生产建议前置网关限流）
    rate_limit_window_seconds: float = Field(default=60.0, gt=0, le=3600)
    rate_limit_max_requests: int = Field(default=60, ge=1, le=10000)
    # 请求体总量上限，必须大于最大的单文件上传限制（默认 STT 的 25 MB）。
    # 仅在声明了 Content-Length 时生效；chunked 传输仍需网关侧兜底。
    max_request_body_bytes: int = Field(default=32 * 1024 * 1024, ge=1024)
    short_term_memory_turns: int = Field(default = 8, ge = 1, le = 50)
    long_term_memory_interval_turns: int = Field(default = 5, ge = 1, le = 50)
    memory_curve_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_ENABLED",
            "MEMORY_CURVE_ENABLED",
            "memory_curve_enabled",
        ),
    )
    memory_curve_max_stability_days: float = Field(
        default=730.0,
        gt=0,
        le=3650,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_MAX_STABILITY_DAYS",
            "memory_curve_max_stability_days",
        ),
    )
    memory_curve_permanent_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_PERMANENT_THRESHOLD",
            "memory_curve_permanent_threshold",
        ),
    )
    memory_curve_clarity_clear: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_CLARITY_CLEAR",
            "memory_curve_clarity_clear",
        ),
    )
    memory_curve_clarity_fuzzy: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_CLARITY_FUZZY",
            "memory_curve_clarity_fuzzy",
        ),
    )
    memory_curve_clarity_fragment: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_CLARITY_FRAGMENT",
            "memory_curve_clarity_fragment",
        ),
    )
    memory_curve_rank_weight_relevance: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_RANK_WEIGHT_RELEVANCE",
            "memory_curve_rank_weight_relevance",
        ),
    )
    memory_curve_rank_weight_retention: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_RANK_WEIGHT_RETENTION",
            "memory_curve_rank_weight_retention",
        ),
    )
    memory_curve_rank_weight_importance: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_RANK_WEIGHT_IMPORTANCE",
            "memory_curve_rank_weight_importance",
        ),
    )
    memory_curve_forgotten_cleanup_days: float = Field(
        default=30.0,
        gt=0,
        validation_alias=AliasChoices(
            "MEMORIA_MEMORY_CURVE_FORGOTTEN_CLEANUP_DAYS",
            "memory_curve_forgotten_cleanup_days",
        ),
    )
    relationship_delta_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "MEMORIA_RELATIONSHIP_DELTA_ENABLED",
            "relationship_delta_enabled",
        ),
    )
    relationship_delta_min: float = Field(
        default=0.0,
        ge=-10.0,
        le=10.0,
        validation_alias=AliasChoices(
            "MEMORIA_RELATIONSHIP_DELTA_MIN",
            "relationship_delta_min",
        ),
    )
    relationship_delta_max: float = Field(
        default=10.0,
        ge=-10.0,
        le=10.0,
        validation_alias=AliasChoices(
            "MEMORIA_RELATIONSHIP_DELTA_MAX",
            "relationship_delta_max",
        ),
    )
    max_output_tokens: int = Field(default = 400, ge = 1, le = 4096)
    world_clock_default_timezone: str = "UTC"
    world_clock_scheduler_interval_seconds: float = Field(default=30.0, gt=0)
    world_clock_scheduler_lease_seconds: int = Field(default=90, ge=5)
    
    # 向量数据库配置
    vector_db_path: str = "./data/chroma_db"
    embedding_model: str = "./models/sentence-transformers/all-MiniLM-L6-v2"
    vector_search_top_k: int = Field(default = 10, ge = 1, le = 50)

    # 世界观知识库 / RAG 配置
    knowledge_storage_path: str = "./data/knowledge"
    knowledge_query_max_chars: int = Field(default=4000, ge=100, le=20000)
    knowledge_retrieval_top_k: int = Field(default=4, ge=1, le=50)
    knowledge_max_chunks_per_document: int = Field(default=3, ge=1, le=20)
    knowledge_similarity_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    knowledge_injection_max_chars: int = Field(default=4000, ge=500, le=50000)
    knowledge_upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    knowledge_pdf_max_pages: int = Field(default=300, ge=1, le=2000)
    knowledge_extract_max_chars: int = Field(default=1_000_000, ge=1000)
    knowledge_chunk_target_tokens: int = Field(default=200, ge=64, le=230)
    knowledge_chunk_overlap_tokens: int = Field(default=36, ge=0, le=80)
    knowledge_chunk_max_tokens: int = Field(default=240, ge=128, le=256)
    
    @model_validator(mode="after")
    def _apply_production_security_defaults(self) -> "Configs":
        """生产环境默认启用 Secure Cookie，避免明文 HTTP 下误配。"""
        if self.memoria_env == "production" and not self.auth_cookie_secure:
            object.__setattr__(self, "auth_cookie_secure", True)
        return self

    @property
    def light_model(self) -> str:
        """
        获取轻量模型名称，如果未配置则返回默认值。
        """
        return self.llm_light_model or self.llm_model
        
@lru_cache
def get_config() -> Configs:
    return Configs()

configs = get_config()
