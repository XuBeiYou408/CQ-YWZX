import time
import logging
import asyncio
from typing import Dict, Any, List
from langchain_core.prompts import PromptTemplate
try:
    from langchain.agents import create_react_agent, AgentExecutor
except ImportError:
    from langchain_classic.agents import create_react_agent, AgentExecutor

from config import AGENT_MAX_ITERATIONS, AGENT_TIMEOUT
from rag.llm import llm, rewrite_llm
from rag.tools import (
    xiangliang_and_bm25_zhaohui,
    jisuanqi_tool,
    wangye_sousuo_tool,
    bing_web_search_tool,
    baidu_web_search_tool,
    wendang_zhaiyao_tool
)
from rag.memory import huode_huibao_jiliu, compact_history

logger = logging.getLogger(__name__)

# ==================== 注册所有 Agent 工具 ====================
gongju_list = [
    xiangliang_and_bm25_zhaohui,
    bing_web_search_tool,
    baidu_web_search_tool,
    wangye_sousuo_tool,
    jisuanqi_tool,
    wendang_zhaiyao_tool
]

# ==================== 定义 ReAct Prompt 模板 ====================
react_prompt = PromptTemplate.from_template(
    "你是一个全能的企业级 AI 技术导师，专门解答技术、架构与开发相关问题。\n"
    "当你被询问关于底层模型或系统运行方式时，请直接诚实、准确地回答：系统基于企业级 RAG 架构与多 Agent 协同打造，支持云端 API 与本地部署模式（支持 LM Studio / 本地大模型）的动态灵活调度，结合向量知识库检索与网页搜索为你提供最精准的技术解答。\n"
    "为了圆满解答用户的问题，你可以分步骤思考并调用以下工具：\n\n"
    "{tools}\n\n"
    "【绝对格式语法协议 (STRICT FORMAT PROTOCOL)】：\n"
    "你的每一次输出必须且只能采用以下两种标准格式之一，禁止产生任何偏差：\n\n"
    "格式一（发起工具调用）：\n"
    "Thought: 思考你目前需要做什么\n"
    "Action: 工具名称，必须是 [{tool_names}] 之一\n"
    "Action Input: 传入工具的参数\n\n"
    "格式二（结束推理并回答）：\n"
    "Thought: 我现在已经掌握了所有必要的信息，可以回答用户了。\n"
    "Final Answer: 最终给用户的详实、准确且有条理的解答。\n\n"
    "【铁律约束与防死循环】：\n"
    "1. 严禁只输出 Thought: 而漏掉 Action: 或 Final Answer:！一旦输出了 Thought:，下一行必须紧跟 Action: 或 Final Answer:！\n"
    "2. 只要调用的搜索或检索工具返回了 [检索观察] 或 Observation，你已获取必要信息，必须在下一步采用【格式二】直接输出 Final Answer，绝对禁止重复发起 Action！\n"
    "3. 如果外部网页搜索或知识库未召回结果，直接结合你自身强大的大模型知识储备输出 Final Answer。\n\n"
    "现在开始！\n\n"
    "历史对话上下文：\n"
    "{chat_history}\n\n"
    "Question: {input}\n"
    "Thought: {agent_scratchpad}"
)

# ==================== 创建 Agent 执行器 ====================
def create_dynamic_agent_executor(target_llm=None):
    use_llm = target_llm or llm
    dyn_agent = create_react_agent(use_llm, gongju_list, react_prompt)
    return AgentExecutor(
        agent=dyn_agent,
        tools=gongju_list,
        verbose=True,
        max_iterations=AGENT_MAX_ITERATIONS,
        handle_parsing_errors=True,
        return_intermediate_steps=True
    )

agent = create_react_agent(llm, gongju_list, react_prompt)
agent_executor = create_dynamic_agent_executor(llm)

# 项目 4 修复：有界 Session Lock 管理，防止内存无限泄漏
_session_locks: Dict[str, asyncio.Lock] = {}
_SESSION_LAST_USED: Dict[str, float] = {}
_MAX_SESSIONS = 10000

def get_session_lock(session_id: str) -> asyncio.Lock:
    """按 Session 获取互斥锁，并对过期的旧 Key 执行 LRU 自动驱逐回收"""
    now = time.monotonic()
    if len(_session_locks) >= _MAX_SESSIONS:
        # 批量驱逐前 10% 最久未使用的锁资源
        oldest_sids = sorted(_SESSION_LAST_USED, key=_SESSION_LAST_USED.get)[:_MAX_SESSIONS // 10]
        for sid in oldest_sids:
            _session_locks.pop(sid, None)
            _SESSION_LAST_USED.pop(sid, None)
    _SESSION_LAST_USED[session_id] = now
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]

def cleanup_session(session_id: str) -> None:
    """清理 Session 异步锁与时间戳记录"""
    _session_locks.pop(session_id, None)
    _SESSION_LAST_USED.pop(session_id, None)

# ==================== 会话执行包装函数 ====================
async def yunxing_agent_session(question: str, session_id: str) -> Dict[str, Any]:
    """
    负责执行多步 Agent 推理，带 Session 有界互斥锁、Claude Code 就地微压缩与 120 秒超时熔断保护。
    """
    lock = get_session_lock(session_id)
    async with lock:
        history = await asyncio.to_thread(huode_huibao_jiliu, session_id)
        messages = await asyncio.to_thread(lambda: history.messages)
        
        # 1. 优化点 (T4): Claude Code 同款就地微压缩 + 强约束摘要
        chat_history_str = await compact_history(messages, rewrite_llm)
        logger.info(f"[Agent] 开始处理会话 {session_id}，历史已微压缩")

        # 2. 优化点 (T10): asyncio.timeout 超时熔断机制 (支持 Python 3.10+ 双向兼容)
        try:
            if hasattr(asyncio, "timeout"):
                async with asyncio.timeout(AGENT_TIMEOUT):
                    response = await agent_executor.ainvoke({
                        "input": question,
                        "chat_history": chat_history_str
                    })
            else:
                response = await asyncio.wait_for(
                    agent_executor.ainvoke({
                        "input": question,
                        "chat_history": chat_history_str
                    }),
                    timeout=AGENT_TIMEOUT
                )
        except asyncio.TimeoutError:
            logger.warning(f"[Agent] 会话 {session_id} 执行超时 ({AGENT_TIMEOUT}s)，触发超时熔断降级")
            return {
                "answer": "抱歉，由于问题复杂度较高或推理时间过长，触发了系统 120 秒安全超时限制。建议简化提示词或分步骤提问。",
                "thought_process": [],
                "tools_used": []
            }
        except Exception as e:
            logger.error(f"[Agent] 推理过程发生异常: {e}")
            return {
                "answer": f"系统推理发生异常: {str(e)}",
                "thought_process": [],
                "tools_used": []
            }
        
        final_output = response.get("output", "")
        intermediate_steps = response.get("intermediate_steps", [])
        
        thought_process = []
        for action, obs in intermediate_steps:
            log = action.log
            thought = log
            if "Action:" in log:
                thought = log.split("Action:")[0].replace("Thought:", "").strip()
                
            thought_process.append({
                "thought": thought,
                "tool": action.tool,
                "tool_input": action.tool_input,
                "observation": str(obs)
            })
            
        await asyncio.to_thread(history.add_user_message, question)
        await asyncio.to_thread(history.add_ai_message, final_output)
        
        return {
            "answer": final_output,
            "thought_process": thought_process,
            "tools_used": list(set([step["tool"] for step in thought_process]))
        }
