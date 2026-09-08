import logging
from typing import Literal
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from rag.llm import rewrite_llm
from utils.resilience import with_retry

logger = logging.getLogger(__name__)

# ==================== 意图识别路由 Prompt ====================
luyou_prompt = ChatPromptTemplate([
    ("system",
     "你是一个智能路由助手，负责将用户的技术提问分类到最合适的处理路径。\n"
     "你必须根据用户问题，只返回以下三个类别名之一，不要包含任何其他字符（如引号、句号、空格或任何解释说明）：\n\n"
     "1. 'simple_rag'：关于知识库中某个具体事实、配置、概念的简单单步查询，不需要复杂分析。\n"
     "   - 示例：'什么是FAISS'，'如何安装PyTorch'，'Chroma的本地路径是什么'\n"
     "2. 'summarize'：明确要求对某个主题、某技术领域的所有内容进行系统性概括、总结、整理或生成大纲的请求。\n"
     "   - 示例：'总结一下关于BGE的所有内容'，'帮我梳理一篇Python教程大纲'，'概括文档的核心要点'\n"
     "3. 'agent'：需要多步推理、调用计算器进行数学计算、需要联网检索最新互联网事实、或者涉及复杂多视角分析的提问。\n"
     "   - 示例：'计算 2**20 * 4 结果是多少'，'知识库外提问：今年高考时间'，'如何调试LangChain？对比并举例说明'\n\n"
     "请严格只输出以下三个字符串之一：'simple_rag'、'summarize'、'agent'。"),
    ("user", "{question}")
])

# ==================== 系统路由逻辑 (T9: 渐进式重试与自愈降级) ====================
@with_retry(max_retries=1, timeout=3.0, fallback="simple_rag")
async def _call_router_llm(question: str, target_llm=None) -> str:
    use_llm = target_llm or rewrite_llm
    luyou_chain = luyou_prompt | use_llm | StrOutputParser()
    return await luyou_chain.ainvoke({"question": question})

async def xitong_luyou(question: str, target_llm=None) -> Literal["simple_rag", "summarize", "agent", "system_meta"]:
    """
    轻量快速的意图分类路由器，支持传入当前运行时 target_llm，内建零延迟规则过滤与自愈降级。
    """
    q_lower = (question or "").strip().lower()
    if any(k in q_lower for k in ["你是谁", "你叫什么", "你的名字", "模型版本", "什么模型", "运行模式", "系统信息", "你是哪个模型", "介绍一下自己"]):
        return "system_meta"
    if any(k in q_lower for k in ["总结一下", "系统概括", "梳理大纲", "整理一下所有", "全文概括", "归纳总结"]):
        return "summarize"
    if any(k in q_lower for k in ["计算器", "等于多少", "计算", "算一下", "联网搜索", "最新新闻", "今天天气", "天气预报"]):
        return "agent"

    # 本地大模型模式直接直通 simple_rag，消除多余 LLM 调用带来的 3~6 秒延迟与排队
    is_local = False
    if target_llm:
        endpoint = str(getattr(target_llm, "openai_api_base", "") or getattr(target_llm, "base_url", ""))
        if "1234" in endpoint or "11434" in endpoint or "localhost" in endpoint or "127.0.0.1" in endpoint:
            is_local = True

    if is_local:
        return "simple_rag"

    try:
        res = await _call_router_llm(question, target_llm)
        category = (res or "").strip().lower().replace("'", "").replace('"', "").replace("`", "")
        for cat in ["summarize", "agent", "simple_rag"]:
            if cat in category:
                return cat
    except Exception as e:
        logger.debug(f"路由分类降级至 simple_rag: {e}")

    return "simple_rag"
