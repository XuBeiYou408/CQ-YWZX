# ==================== 1. 强力静音消红防御塔（必须放在最顶部） ====================
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"  # 解决 Windows 上 OpenMP 冲突导致的 Python 闪退

# 自适应检测本地 Embedding 权重：本地存在时强制 100% 离线，无外部网络请求；缺失时允许通过镜像源自动拉取
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_default_local_bge = os.path.join(_base_dir, 'data', 'models', 'bge-base-zh-v1.5')
if os.path.isdir(_default_local_bge):
    os.environ["HF_HUB_OFFLINE"] = "1"
else:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import warnings
import numpy
import scipy
import sklearn  # 必须在 sentence_transformers 之前导入，解决 Windows MKL/OpenMP DLL 冲突
import transformers
transformers.utils.logging.set_verbosity_error()#强制 HuggingFace 的 transformers 库关闭所有非错误的提示
warnings.filterwarnings("ignore")  # 屏蔽所有 Python 级别的警告（Deprecation, UserWarning 等）
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"  # 彻底关闭 Windows 符号链接警告
os.environ["TOKENIZERS_PARALLELISM"] = "false"  # 关闭分词器多线程死锁警告
import logging
logging.getLogger("transformers").setLevel(logging.ERROR)  # 彻底闭住 Transformers 库的嘴
logging.getLogger("chromadb").setLevel(logging.ERROR)  # 闭住 Chroma 数据库的非必要日志
# 闭住 langchain_openai 的嘴（消除系统代理检测提示）
logging.getLogger("langchain_openai").setLevel(logging.WARNING)
# 闭住 sentence_transformers 的嘴（消除本地模型加载路径提示）
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
# 顺便闭住 httpx 的嘴（防止后续密密麻麻的 API 请求网络日志刷屏）
logging.getLogger("httpx").setLevel(logging.WARNING)