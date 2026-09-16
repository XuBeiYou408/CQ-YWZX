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
     "你是一个企业本地智能知识库意图路由助手，负责将用户提问精准分类到最匹配的处理路径。\n"
     "你必须只返回以下三个类别名之一，严禁包含任何其他字符、标点、引号或解释说明：\n\n"
     "1. 'simple_rag'：关于企业规章、考勤休假、差旅报销、数据保密、入职指引等内部制度的单步查询与事实问答。\n"
     "   - 示例：'公司年假有几天'，'出差住宿标准上限是多少'，'新员工入职电脑怎么申领'，'研发保密红线有哪些'\n"
     "2. 'summarize'：要求对所有制度清单进行梳理、查看制度目录、或对某类规章做全局大纲总结的请求。\n"
     "   - 示例：'公司有哪些规章制度'，'查看制度目录'，'全面总结一下考勤与差旅的所有核心要点'\n"
     "3. 'agent'：涉及数学数值核算（如扣除工资、补贴汇总）、知识库外最新法规检索、或多步骤复合推演的提问。\n"
     "   - 示例：'请假2.5天扣多少工资'，'国家2026年最新年休假条例规定'，'查一下出差标准并查一下明天的天气'\n\n"
     "请严格只输出以下三个字符串之一：'simple_rag'、'summarize'、'agent'。"),
    ("user", "{question}")
])

# ==================== 系统路由逻辑 ====================
@with_retry(max_retries=1, timeout=3.0, fallback="simple_rag")
async def _call_router_llm(question: str, target_llm=None) -> str:
    use_llm = target_llm or rewrite_llm
    luyou_chain = luyou_prompt | use_llm | StrOutputParser()
    return await luyou_chain.ainvoke({"question": question})

async def xitong_luyou(question: str, target_llm=None) -> Literal["simple_rag", "summarize", "agent", "system_meta"]:
    """
    轻量快速的意图分类路由器，支持零延迟规则极速直通与自愈降级。
    """
    q_lower = (question or "").strip().lower()
    
    # 1. 极速系统元信息识别
    if any(k in q_lower for k in ["你是谁", "你叫什么", "你的名字", "模型版本", "什么模型", "运行模式", "系统信息", "你是哪个模型", "介绍一下自己"]):
        return "system_meta"
        
    # 2. 制度大纲与清单探查识别
    if any(k in q_lower for k in ["制度清单", "所有制度", "有哪些制度", "制度目录", "规章清单", "有哪些规章", "清单", "目录", "全景", "总结一下", "系统概括", "梳理大纲", "全文概括", "归纳总结"]):
        return "summarize"
        
    # 3. 确定性计算与外部时效识别 -> 直通 Agent
    if any(k in q_lower for k in ["计算器", "等于多少", "计算", "算一下", "扣除多少", "扣发", "扣多少钱", "联网搜索", "最新新闻", "今天天气", "天气预报", "国家规定", "外网", "航班", "飞机票", "最新"]):
        return "agent"

    # 4. 本地端侧大模型模式：默认单步问题直通 simple_rag 快车道（1~2秒），消除排队
    is_local = False
    if target_llm:
        endpoint = str(getattr(target_llm, "openai_api_base", "") or getattr(target_llm, "base_url", ""))
        if "1234" in endpoint or "11434" in endpoint or "localhost" in endpoint or "127.0.0.1" in endpoint:
            is_local = True

    if is_local:
        return "simple_rag"

    # 5. 云端模型模式下通过轻量级 LLM 判定
    try:
        res = await _call_router_llm(question, target_llm)
        category = (res or "").strip().lower().replace("'", "").replace('"', "").replace("`", "")
        for cat in ["summarize", "agent", "simple_rag"]:
            if cat in category:
                return cat
    except Exception as e:
        logger.debug(f"路由分类降级至 simple_rag: {e}")

    return "simple_rag"
