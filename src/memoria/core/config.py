"""
应用全局配置。所有配置项通过环境变量 / .env 文件注入，
方便在不同模型供应商之间切换，无需改代码。
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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
    
    # 轻量任务专用 LLM 配置（可选，留空则使用主 LLM）
    llm_light_base_url: str = ""
    llm_light_api_key: SecretStr = ""

    # OpenAI Speech 配置（与角色对话模型独立）
    speech_api_key: SecretStr = ""
    speech_base_url: str = "https://api.openai.com/v1"
    speech_stt_model: str = "gpt-4o-mini-transcribe"
    speech_tts_model: str = "gpt-4o-mini-tts"
    speech_output_format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "wav"
    speech_storage_path: str = "./data/speech"
    speech_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    speech_stt_upload_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    speech_custom_voice_upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    speech_cache_max_age_seconds: int = Field(default=7 * 24 * 60 * 60, ge=0)
    speech_cache_max_bytes: int = Field(default=512 * 1024 * 1024, ge=0)
    
    # 应用配置
    database_path: str = "./data/sqlite_db/memoria.db"
    database_url: str = ""
    auth_cookie_secure: bool = False
    short_term_memory_turns: int = Field(default = 8, ge = 1, le = 50)
    long_term_memory_interval_turns: int = Field(default = 5, ge = 1, le = 50)
    max_output_tokens: int = Field(default = 600, ge = 1, le = 4096)
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
    knowledge_retrieval_top_k: int = Field(default=6, ge=1, le=50)
    knowledge_max_chunks_per_document: int = Field(default=3, ge=1, le=20)
    knowledge_similarity_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    knowledge_injection_max_chars: int = Field(default=6000, ge=500, le=50000)
    knowledge_upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    knowledge_pdf_max_pages: int = Field(default=300, ge=1, le=2000)
    knowledge_extract_max_chars: int = Field(default=1_000_000, ge=1000)
    knowledge_chunk_target_tokens: int = Field(default=200, ge=64, le=230)
    knowledge_chunk_overlap_tokens: int = Field(default=36, ge=0, le=80)
    knowledge_chunk_max_tokens: int = Field(default=240, ge=128, le=256)
    
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
