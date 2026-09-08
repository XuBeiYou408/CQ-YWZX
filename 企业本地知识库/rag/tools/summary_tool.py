from langchain.tools import tool
from rag.retriever import zhaohui_and_rerank
from rag.llm import llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ==================== 定义文档摘要提示词 ====================
zhaiyao_prompt = ChatPromptTemplate([
    ("system", 
     "你是一个专业的技术文档摘要助手。请严格基于以下从知识库中检索到的技术资料，生成一份结构清晰、核心内容突出的技术摘要。\n"
     "要求：\n"
     "1. 提取出所有关键概念、核心 API 用法、配置项以及底层工作原理。\n"
     "2. 必须以 Markdown 格式输出，多使用无序列表、小标题和代码块，避免长篇大论。\n"
     "3. 必须客观严谨，如果资料不足或无相关信息，请直接指出。\n\n"
     "【参考资料】:\n{context}"),
    ("user", "请针对主题 '{topic}' 生成一份详实的技术总结与摘要。")
])

# ==================== 封装文档摘要工具为 Tool ====================
@tool
async def wendang_zhaiyao_tool(topic: str) -> str:
    """
    在知识库中全面检索某个技术主题相关的文档并生成结构化摘要。
    适用于：用户要求“总结关于 X 的内容”、“整理 Y 的概念”、“做一篇关于 Z 的概述”等分析总结类问题。
    输入：要总结的技术主题、关键词或库的名称。
    输出：大模型基于检索文档生成的结构化摘要。
    """
    try:
        # 1. 检索相关的 Document 列表 (R2-H3 调整安全上限)
        docs = await zhaohui_and_rerank(topic, rerank_limit=8, return_documents=True)
        if not docs:
            return f"抱歉，在知识库中未检索到任何关于 '{topic}' 的相关资料，无法生成摘要。"
        
        # 2. 格式化上下文
        context_list = []
        for idx, doc in enumerate(docs, start=1):
            source = doc.metadata.get('source', '未知文件')
            context_list.append(f"[文档{idx}] 来源: {source}\n{doc.page_content}")
            
        # R2-H3 修复：引入 Token / 字符预算截断，防止爆主 LLM 窗口
        MAX_CONTEXT_CHARS = 6000
        truncated_context = []
        total_chars = 0
        for item in context_list:
            if total_chars + len(item) > MAX_CONTEXT_CHARS:
                break
            truncated_context.append(item)
            total_chars += len(item)
            
        context_str = "\n\n".join(truncated_context)
        
        # 3. 调用大模型生成摘要
        zhaiyao_chain = zhaiyao_prompt | llm | StrOutputParser()
        result = await zhaiyao_chain.ainvoke({
            "context": context_str,
            "topic": topic
        })
        return result
    except Exception as e:
        return f"摘要生成失败：{str(e)}"
