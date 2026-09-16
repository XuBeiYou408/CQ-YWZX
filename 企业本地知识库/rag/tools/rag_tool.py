import logging
from langchain.tools import tool
from rag.retriever import zhaohui_and_rerank

logger = logging.getLogger(__name__)

# ==================== 封装本地企业规章库检索为 Tool ====================
@tool
async def enterprise_kb_search(query: str) -> str:
    """
    在本地企业知识库中精准检索规章制度、管理办法、报销流程、考勤规范等技术与行政文件。
    适用于：任何关于企业内部政策、福利待遇、出差报销、保密协议、入职流程等制度查询。
    输入：具体的查询问题或核心关键词。
    输出：本地向量数据库与BM25混合检索重排后的权威规章段落与条款出处。
    """
    try:
        shuju = await zhaohui_and_rerank(query, rerank_limit=10)
        if not shuju or not str(shuju).strip():
            return "【🏢 本地企业规章库】：在本地知识库中未检索到高度相关的明文条款。建议结合制度目录探查或进行外网时效检索。"
        return f"【🏢 本地企业规章库检索结果】:\n{shuju}"
    except Exception as e:
        logger.error(f"检索知识库异常: {e}")
        return f"检索本地知识库时发生错误: {str(e)}"

# 保持向后兼容旧命名
xiangliang_and_bm25_zhaohui = enterprise_kb_search
