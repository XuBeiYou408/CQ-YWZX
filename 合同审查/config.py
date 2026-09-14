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

    # Agent 化改造预算配置（融合终版计划书 §3.4 收敛控制）
    AGENT_ENABLED: bool = os.getenv("AGENT_ENABLED", "1") == "1"
    AGENT_MODEL: str = os.getenv("AGENT_MODEL", "")                                      # 指定 Agent 用模型（留空则自动优选）

    # ---------- 审查用哪个模型（跟随会话） ----------
    # "session"（默认）：跟随「当前 WorkBuddy 会话正在使用的模型」
    #   · 会话用的是本地模型（custom-local:*）→ 就用那个本地模型
    #   · 会话用的是云端模型且已在 ~/.workbuddy/models.json 登记同名接入 → 走该云端接入
    #   · 会话用的是云端模型但未登记 → 工具无凭据，回退本机 LM Studio 并在结果中说明原因
    # "local"  ：旧行为，只看本机 LM Studio 的已加载/可用模型
    # "pinned" ：始终使用 AGENT_MODEL（为空则 DEFAULT_MODEL）
    MODEL_POLICY: str = os.getenv("MODEL_POLICY", "session")
    # 平台状态文件位置（用于读取当前会话模型；一般无需修改）
    WORKBUDDY_DIR: str = os.getenv("WORKBUDDY_DIR", os.path.join(os.path.expanduser("~"), ".workbuddy"))
    AGENT_TIME_BUDGET_SECONDS: int = int(os.getenv("AGENT_TIME_BUDGET_SECONDS", "1500"))  # 全局时间预算
    AGENT_MAX_DEEP_DIVE: int = int(os.getenv("AGENT_MAX_DEEP_DIVE", "5"))               # 深查预算（含快筛升级）
    AGENT_MAX_TOOL_ROUNDS_PER_CLAUSE: int = 3   # 单条款工具调用轮次上限
    AGENT_MAX_RETRY_PER_CLAUSE: int = 2         # 单条款 self-check 重取证上限
    AGENT_GLOBAL_REFLECT_ROUNDS: int = 1        # 全局反思回环上限
    AGENT_SMALL_CONTRACT_CLAUSES: int = 8       # 条款 < 8 → 跳过规划走旧管道
    AGENT_SMALL_CONTRACT_CHARS: int = 2000      # 字数 < 2000 → 跳过规划走旧管道

    # 平台标识
    PLATFORM_TAG: str = "合同审查 AGENT · 本地端侧"

config = AppConfig()
