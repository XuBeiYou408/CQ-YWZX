import asyncio
import concurrent.futures
from operator import itemgetter
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

from rag.llm import llm
from rag.prompts import huode_llm_prompt
from rag.retriever import zhaohui_and_rerank

def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)

# ==================== 问答链的组装 ====================
def create_qa_chain(target_llm=None, provider="cloud", model_name="deepseek-chat"):
    use_llm = target_llm or llm
    dynamic_prompt = huode_llm_prompt(provider, model_name)

    async def _async_get_context(inp):
        q = inp.get('input') if isinstance(inp, dict) else str(inp)
        return await zhaohui_and_rerank({'input': q, 'target_llm': use_llm})

    def _sync_get_context(inp):
        q = inp.get('input') if isinstance(inp, dict) else str(inp)
        return _run_coro_sync(zhaohui_and_rerank({'input': q, 'target_llm': use_llm}))

    def _get_input_str(inp):
        return inp.get('input') if isinstance(inp, dict) else str(inp)

    return (
        {
            'context': RunnableLambda(func=_sync_get_context, afunc=_async_get_context),
            'input': RunnableLambda(func=_get_input_str)
        }
        | dynamic_prompt
        | use_llm
        | StrOutputParser()
    )

# 默认兼容实例
question_answer_chain = create_qa_chain(llm)
