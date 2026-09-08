import re
import logging
from typing import List
from rag.llm import rewrite_llm
from rag.prompts import rewrite_prompt
from utils.resilience import with_retry

logger = logging.getLogger(__name__)

# ==================== 定义查询重写（Rewrite）行为 (T9) ====================
@with_retry(max_retries=1, timeout=3.0, fallback=None)
async def _call_rewrite_llm(question: str, target_llm=None):
    use_llm = target_llm or rewrite_llm
    return await use_llm.ainvoke(rewrite_prompt.format_messages(question=question))

async def question_rewriter(question: str, target_llm=None) -> List[str]:
    # 短查询（如“模型版本是”、“什么是FAISS”）无需额外扩写，直接秒级召回
    if len((question or "").strip()) <= 8:
        return [question]

    try:
        response = await _call_rewrite_llm(question, target_llm)
        if response is None:
            return [question]
        raw_text = response.content
    except Exception as e:
        logger.warning(f"查询重写过程触发异常 ({e})，降级使用原始问题")
        return [question]

    rewrites = raw_text.strip().split('\n')
    cleaned_rewrites = []
    for rew in rewrites:
        rew_str = rew.strip()
        if rew_str and not rew_str.startswith(("好的", "这是", "以下", "要求")):
            cleaned_q = re.sub(r'^\d+[\s\.\)、\-]*', '', rew_str).strip()
            if cleaned_q:
                cleaned_rewrites.append(cleaned_q)
                
    queries = [question] + cleaned_rewrites[:2]

    if len(queries) <= 1:
        logger.warning(f"查询重写结果未生成附加视角，原始响应: {raw_text[:60]}")
    else:
        short_q = question[:40] + "..." if len(question) > 40 else question
        logger.info(f"查询重写成功: \"{short_q}\" → 生成 {len(queries)} 个多维度视角")

    return queries
