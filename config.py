import os
import subprocess
import sys
from dotenv import load_dotenv

# ==================== 国内模型镜像源加速与环境自愈 ====================
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# ==================== CUDA 安全检测与自动降级 ====================
def _jian_ce_cuda_anquan() -> bool:
    if "ANTIGRAVITY_TRAJECTORY_ID" in os.environ:
        return False
    try:
        res = subprocess.run(
            [sys.executable, "-c", "import torch; torch.zeros(1).cuda()"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3
        )
        return res.returncode == 0
    except Exception:
        return False

if not _jian_ce_cuda_anquan():
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetEnvironmentVariableW("CUDA_VISIBLE_DEVICES", "-1")
        except Exception:
            pass

# 解决 Windows 上多个 OpenMP DLL (libiomp5md.dll) 冲突导致的 process exit(1) 闪退
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# ==================== 本地数据的读取 ====================
load_dotenv()
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_raw_folder = os.getenv('YUAN_SUCAI_PATH')
folder_path = os.path.join(_BASE_DIR, 'data', 'documents')
if _raw_folder:
    try:
        os.makedirs(_raw_folder, exist_ok=True)
        folder_path = _raw_folder
    except Exception:
        pass
os.makedirs(folder_path, exist_ok=True)

_raw_db = os.getenv('LOCAL_DB_PATH')
LOCAL_DB_PATH = os.path.join(_BASE_DIR, 'data', 'faiss_db')
if _raw_db:
    try:
        os.makedirs(_raw_db, exist_ok=True)
        LOCAL_DB_PATH = _raw_db
    except Exception:
        pass
os.makedirs(LOCAL_DB_PATH, exist_ok=True)

REDIS_URL = os.getenv('REDIS_URL', None)
CACHE_HMAC_KEY = os.getenv('CACHE_HMAC_KEY', '')

# 安全鉴权与 API Keys（修复 A：支持显式 AUTH_ENABLED 开关控制）
API_KEYS = set([k.strip() for k in os.getenv('API_KEYS', '').split(',') if k.strip()])
AUTH_ENABLED = os.getenv('AUTH_ENABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')

# 启动校验 (项目 3 修复: 校验关键环境变量)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:1234/v1")
if not DEEPSEEK_API_KEY:
    import warnings
    warnings.warn("警告：缺少环境变量 DEEPSEEK_API_KEY，如使用云端模型请在设置页面或 .env 中配置", UserWarning)

# ==================== 统一系统超参数配置区 ====================
# 检索链路配置
TOP_K_RECALL: int = 35          # 向量/BM25 单路召回数
TOP_K_RERANK: int = 5           # Reranker 精排后保留数
RERANK_LIMIT: int = 45          # Reranker 输入截断水位线
REWRITE_QUERY_COUNT: int = 2    # 查询重写扩展视角数

# Agent 调度配置
AGENT_MAX_ITERATIONS: int = 8   # Agent 最大推理步数
AGENT_TIMEOUT: int = 120        # Agent 单次会话总超时（秒）

# 记忆与上下文配置 (Claude Code 风格微压缩)
REDIS_TTL: int = 7200           # Redis 会话缓存 TTL（秒）
CONTEXT_MAX_TOKENS: int = 4000  # 上下文窗口总 Token 预算
COMPACTION_THRESHOLD: int = 3000 # 触发微压缩的 Token 阈值

# 模型推理与网络配置
EMBEDDING_BATCH_SIZE: int = 64  # Embedding 推理批次大小
LLM_REQUEST_TIMEOUT: int = 30   # LLM API 超时（秒）
