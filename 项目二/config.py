"""
智审 (Doc-Agent) - 系统运行配置文件
"""
import os
from pydantic import BaseModel

class AppConfig(BaseModel):
    PORT: int = int(os.getenv("PORT", "8020"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # LM Studio 本地推理配置 (统一接入端口 1234)
    LM_STUDIO_BASE_URL: str = os.getenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    LM_STUDIO_API_KEY: str = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "qwen2.5-14b-instruct")

    # 审查默认参数
    DEFAULT_TEMPERATURE: float = 0.15
    MAX_OUTPUT_TOKENS: int = 4096

    # 平台标识
    PLATFORM_TAG: str = "合同审查 AGENT · 本地端侧"

config = AppConfig()
