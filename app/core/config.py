"""
应用全局配置。所有配置项通过环境变量 / .env 文件注入，
方便在不同模型供应商之间切换，无需改代码。
"""

from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Configs(BaseSettings):
    """
    全局配置类，包含所有应用需要的配置项。
    """

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        env_prefix="APP_",
        extra="forbid")
    
    # LLM 配置
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: SecretStr = ""
    llm_model: str = "deepseek-chat"
    llm_light_model: str = ""
    
    #应用配置
    database_url: Path = Path("sqlite:///./memoria.db")
    short_term_memory_turns: int = Field(default = 8, ge = 1, le = 50)
    max_output_tokens: int = Field(default = 600, ge = 1, le = 4096)
    
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