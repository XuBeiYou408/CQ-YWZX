from langchain.tools import tool
from rag.retriever import zhaohui_and_rerank

# ==================== 封装知识库召回和重排为 Tool ====================
@tool
async def xiangliang_and_bm25_zhaohui(query: str) -> str:
    """
    在知识库中搜索与问题相关的技术文档和资料。
    适用于：需要获取本地知识库、产品文档、代码教程、LangChain 或 BGE 模型的底层原理等问题。
    输入：具体的查询问题或关键词。
    输出：从知识库中召回并经过重排的参考资料片段。
    """
    try:
        shuju = await zhaohui_and_rerank(query, rerank_limit=15)
        return shuju
    except Exception as e:
        return f"检索知识库时发生错误: {str(e)}"
