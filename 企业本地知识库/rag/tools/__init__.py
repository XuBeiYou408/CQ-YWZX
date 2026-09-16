from rag.tools.rag_tool import xiangliang_and_bm25_zhaohui, enterprise_kb_search
from rag.tools.calculator_tool import jisuanqi_tool, policy_calculator
from rag.tools.web_search_tool import (
    unified_web_search,
    wangye_sousuo_tool,
    bing_web_search_tool,
    baidu_web_search_tool
)
from rag.tools.doc_catalog_tool import doc_catalog_inspector
from rag.tools.summary_tool import wendang_zhaiyao_tool

# ==================== 统一导出所有 Agent 调用的工具 ====================
__all__ = [
    "enterprise_kb_search",
    "policy_calculator",
    "doc_catalog_inspector",
    "unified_web_search",
    # 兼容旧命名
    "xiangliang_and_bm25_zhaohui",
    "jisuanqi_tool",
    "wangye_sousuo_tool",
    "bing_web_search_tool",
    "baidu_web_search_tool",
    "wendang_zhaiyao_tool"
]
