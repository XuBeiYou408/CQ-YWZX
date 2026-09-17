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
    # 审查模型（2026-09-17 起内置默认固定为端侧主力模型 google/gemma-4-e4b）
    # 说明：实际用哪个模型由「模型管理」面板（model_config.json）决定，本项仅是最终兜底默认值。
    # 需要临时换模型：① 前端「模型管理」面板选择（推荐）；② 设环境变量 AGENT_MODEL（硬锁定，优先级更高）。
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "google/gemma-4-e4b")

    # 审查默认参数
    DEFAULT_TEMPERATURE: float = 0.15
    MAX_OUTPUT_TOKENS: int = 4096

    # Agent 化改造预算配置（融合终版计划书 §3.4 收敛控制）
    AGENT_ENABLED: bool = os.getenv("AGENT_ENABLED", "1") == "1"
    # 审查模型硬锁定（管理员级）：留空 = 由「模型管理」面板决定（默认行为）
    AGENT_MODEL: str = os.getenv("AGENT_MODEL", "")
    AGENT_TIME_BUDGET_SECONDS: int = int(os.getenv("AGENT_TIME_BUDGET_SECONDS", "1500"))  # 全局时间预算
    AGENT_MAX_DEEP_DIVE: int = int(os.getenv("AGENT_MAX_DEEP_DIVE", "3"))               # 深查预算（含快筛升级）；2026-09-15 由 5 降为 3：深查 +1 条 ≈ +50s/次模型调用
    AGENT_MAX_TOOL_ROUNDS_PER_CLAUSE: int = 3   # 单条款工具调用轮次上限
    AGENT_MAX_RETRY_PER_CLAUSE: int = 2         # 单条款 self-check 重取证上限
    AGENT_GLOBAL_REFLECT_ROUNDS: int = 1        # 全局反思回环上限
    # 全量合同 Agent 化：彻底去除门槛要求，所有合同均走 Agent 闭环（感知→规划→行动→反思 + 思维链）
    AGENT_SMALL_CONTRACT_CLAUSES: int = int(os.getenv("AGENT_SMALL_CONTRACT_CLAUSES", "0"))      # 阈值置 0：不再跳过
    AGENT_SMALL_CONTRACT_CHARS: int = int(os.getenv("AGENT_SMALL_CONTRACT_CHARS", "0"))          # 阈值置 0：不再跳过

    # 平台标识
    PLATFORM_TAG: str = "合同审查 AGENT · 本地端侧"

config = AppConfig()
