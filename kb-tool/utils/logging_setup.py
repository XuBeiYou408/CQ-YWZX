import logging
import sys

def setup_logging(level=logging.INFO) -> None:
    """
    配置全局结构化日志输出，并在 Windows 环境下安全初始化 UTF-8 格式，
    杜绝捕获 UnicodeEncodeError 的 print 反模式。
    """
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, 'reconfigure'):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-5s | %(name)-18s | %(message)s",
        datefmt="%H:%M:%S",
        force=True
    )

logger = logging.getLogger("rag-enterprise")
