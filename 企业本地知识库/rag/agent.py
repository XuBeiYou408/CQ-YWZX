import re
import time
import json
import logging
import asyncio
from typing import Dict, Any, List, Tuple, AsyncGenerator

from config import AGENT_MAX_ITERATIONS, AGENT_TIMEOUT
from rag.llm import llm, rewrite_llm, huode_dongtai_llm
from rag.tools import (
    enterprise_kb_search,
    policy_calculator,
    doc_catalog_inspector,
    unified_web_search,
    xiangliang_and_bm25_zhaohui,
    jisuanqi_tool,
    wangye_sousuo_tool,
    bing_web_search_tool,
    baidu_web_search_tool,
    wendang_zhaiyao_tool
)
from rag.memory import huode_huibao_jiliu, compact_history

logger = logging.getLogger(__name__)

# ==================== 工具集与字典注册 ====================
gongju_list = [
    enterprise_kb_search,
    policy_calculator,
    doc_catalog_inspector,
    unified_web_search,
    # 兼容旧工具
    xiangliang_and_bm25_zhaohui,
    jisuanqi_tool,
    wangye_sousuo_tool,
    bing_web_search_tool,
    baidu_web_search_tool,
    wendang_zhaiyao_tool
]

_TOOLS_MAP = {
    "enterprise_kb_search": enterprise_kb_search,
    "policy_calculator": policy_calculator,
    "doc_catalog_inspector": doc_catalog_inspector,
    "unified_web_search": unified_web_search,
    # 映射兼容
    "xiangliang_and_bm25_zhaohui": enterprise_kb_search,
    "jisuanqi_tool": policy_calculator,
    "calculator": policy_calculator,
    "doc_catalog": doc_catalog_inspector,
    "web_search": unified_web_search,
    "wangye_sousuo_tool": unified_web_search,
    "bing_web_search_tool": unified_web_search,
    "baidu_web_search_tool": unified_web_search,
    "wendang_zhaiyao_tool": enterprise_kb_search
}

# ==================== 兼容 LangChain Action / Step 数据桩 ====================
class AgentActionStub:
    def __init__(self, tool: str, tool_input: str, log: str):
        self.tool = tool
        self.tool_input = tool_input
        self.log = log

    def __repr__(self):
        return f"AgentActionStub(tool={self.tool}, tool_input={self.tool_input})"

class AgentStepStub(tuple):
    """双向兼容 tuple(action, observation) 与 .action / .observation 属性访问"""
    def __new__(cls, action: AgentActionStub, observation: str):
        return super(AgentStepStub, cls).__new__(cls, (action, observation))

    @property
    def action(self) -> AgentActionStub:
        return self[0]

    @property
    def observation(self) -> str:
        return self[1]

# ==================== 辅助方法：清洗端侧 Reasoning 标签与解析 ====================
def _clean_reasoning_and_get_thought(raw_text: str) -> Tuple[str, str]:
    """
    智能分离端侧思考模型（如 DeepSeek-R1 / Qwen 等）输出的 <think>...</think> 标签，
    确保思考过程能正常送往前端显示，同时防止底层正则解析失败崩溃。
    """
    extracted_thought = ""
    clean_text = raw_text or ""
    
    think_match = re.search(r'<think>(.*?)(?:</think>|$)', clean_text, re.DOTALL | re.IGNORECASE)
    if think_match:
        extracted_thought = think_match.group(1).strip()
        clean_text = re.sub(r'<think>.*?(?:</think>|$)', '', clean_text, flags=re.DOTALL | re.IGNORECASE).strip()
        
    return clean_text, extracted_thought

async def _execute_tool_safe(tool_name: str, tool_input: str) -> str:
    """带 5 秒超时保护与安全容错的工具分发执行器"""
    target = _TOOLS_MAP.get(tool_name.strip().lower())
    if not target:
        # 模糊匹配容错
        for k, v in _TOOLS_MAP.items():
            if k in tool_name.lower():
                target = v
                break
                
    if not target:
        return f"【工具执行告警】：未找到名为 '{tool_name}' 的工具。"

    clean_arg = str(tool_input or "").strip().strip('"').strip("'")
    try:
        if hasattr(target, "ainvoke"):
            res = await asyncio.wait_for(target.ainvoke(clean_arg), timeout=5.0)
        elif hasattr(target, "invoke"):
            res = await asyncio.wait_for(asyncio.to_thread(target.invoke, clean_arg), timeout=5.0)
        elif asyncio.iscoroutinefunction(target):
            res = await asyncio.wait_for(target(clean_arg), timeout=5.0)
        else:
            res = await asyncio.wait_for(asyncio.to_thread(target, clean_arg), timeout=5.0)
        return str(res)
    except asyncio.TimeoutError:
        return f"[⚡ 工具超时拦截]: 工具 {tool_name} 执行超过 5 秒已自动熔断，降级由端侧知识库综合回答。"
    except Exception as e:
        logger.error(f"调用工具 {tool_name} 异常: {e}")
        return f"[⚠️ 工具执行异常]: {str(e)}"

# ==================== 现代化双轨 Agent 规划与执行器 ====================
class EnterpriseAgentExecutor:
    """
    面向华硕本地大模型售前演示的现代化自适应状态机 Agent 执行器：
    - 阶段一：Perceive & Plan (感知意图并生成极简确定性步骤)
    - 阶段二：Act & Dispatch (调用本地知识库/算力沙箱/统一外网检索)
    - 阶段三：Synthesize (综合输出并标注溯源出处)
    彻底告别老旧文本正则 ReAct 的死锁超时，全程控制在 3~6 秒内收敛。
    """
    def __init__(self, target_llm=None):
        self.target_llm = target_llm or llm

    async def astream(self, inputs: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        question = inputs.get("input", "")
        chat_history_str = inputs.get("chat_history", "")
        
        # 规划提示词
        plan_system = (
            "你是一个企业本地智能知识库与业务合规助手，运行在私有化硬件端侧环境。\n"
            "为了准确回答用户问题，你可以选择调用以下 4 个专用工具之一：\n"
            "1. enterprise_kb_search: 本地企业知识库检索（企业考勤、请假、差旅报销、数据保密、新员工入职等规章制度）。\n"
            "2. policy_calculator: 合规沙箱计算器，严谨计算数学表达式（如请假工资扣除、差旅住宿补贴累加、天数计算）。\n"
            "3. doc_catalog_inspector: 探查当前本地知识库收录的全部制度文件全景清单与大纲。\n"
            "4. unified_web_search: 智能外网时效检索（查询外部国家法规、行业新闻、天气、航班等超纲问题）。\n\n"
            "【决策输出格式规范】：\n"
            "如果需要调用工具，请严格输出：\n"
            "Thought: 简要说明你的规划（1行）\n"
            "Action: 工具名称（必须是 enterprise_kb_search / policy_calculator / doc_catalog_inspector / unified_web_search 之一）\n"
            "Action Input: 传入工具的具体入参\n\n"
            "如果你无需工具即可基于已知信息回答，请输出：\n"
            "Thought: 信息已充分，输出结论\n"
            "Final Answer: 你的完整解答"
        )

        user_content = f"历史对话:\n{chat_history_str}\n\n当前用户提问: {question}"
        observations: List[Tuple[str, str, str]] = []  # (tool_name, tool_input, obs)

        # 步数硬预算：最多 2 轮工具调用，单次总时长 ≤ 15 秒强制收敛
        loop_start = time.time()
        max_steps = min(AGENT_MAX_ITERATIONS, 2)
        final_answer = ""

        for step_idx in range(max_steps):
            if time.time() - loop_start > 12.0:
                logger.warning("Agent 步骤耗时触及安全水位线，强制启动综合收尾")
                break

            prompt_msgs = [
                ("system", plan_system),
                ("user", user_content)
            ]
            if observations:
                obs_summary = "\n\n".join([f"【工具 {t} 反馈 (入参: {inp})】:\n{obs}" for t, inp, obs in observations])
                prompt_msgs.append(("assistant", f"Thought: 正在根据工具反馈推进...\n\n已获取事实:\n{obs_summary}"))
                prompt_msgs.append(("user", "请根据以上事实继续：输出下一步 Action，或输出 Final Answer 完成回答。"))

            try:
                # 尝试调用决策模型
                resp = await asyncio.wait_for(self.target_llm.ainvoke(prompt_msgs), timeout=8.0)
                raw_out = resp.content if hasattr(resp, "content") else str(resp)
            except Exception as e:
                logger.warning(f"Agent 决策 LLM 响应异常或超时: {e}，自动启用直连兜底")
                raw_out = ""

            clean_text, thought_inside = _clean_reasoning_and_get_thought(raw_out)

            # 1. 检查是否直接包含了 Final Answer
            if "Final Answer:" in clean_text:
                final_answer = clean_text.split("Final Answer:", 1)[1].strip()
                thought_str = thought_inside or "综合所有信息，完成最终业务解答。"
                yield {"actions": [AgentActionStub("final", "", f"Thought: {thought_str}")]}
                break

            # 2. 解析 Action 与 Action Input
            tool_match = re.search(r'Action:\s*([a-zA-Z0-9_-]+)', clean_text)
            input_match = re.search(r'Action Input:\s*(.+)', clean_text, re.DOTALL)
            
            selected_tool = tool_match.group(1).strip() if tool_match else None
            tool_arg = input_match.group(1).strip() if input_match else question

            # 启发式自愈：若第一轮模型未按格式输出 Action 但文字里提及需要查询某事，自动识别工具
            if not selected_tool and step_idx == 0:
                q_lower = question.lower()
                if any(op in question for op in ["+", "-", "*", "/", "**", "%"]) and any(c.isdigit() for c in question):
                    selected_tool = "policy_calculator"
                    math_chars = "".join([c for c in question if c.isdigit() or c in "+-*/.() "])
                    tool_arg = math_chars.strip()
                elif any(k in q_lower for k in ["哪些制度", "制度清单", "目录", "全景", "有哪些文件", "规章清单"]):
                    selected_tool = "doc_catalog_inspector"
                    tool_arg = "全部"
                elif any(k in q_lower for k in ["最新", "天气", "航班", "今天", "全国", "国家规定", "外网"]):
                    selected_tool = "unified_web_search"
                    tool_arg = question
                elif len(observations) == 0:
                    selected_tool = "enterprise_kb_search"
                    tool_arg = question

            if not selected_tool:
                # 无法解析且无需工具，将文本作为最终答案
                final_answer = clean_text if clean_text else "已结合本地知识库为您完成分析。"
                break

            # 徽章化视觉提示
            badge_name = {
                "enterprise_kb_search": "🔒 本地规章检索",
                "policy_calculator": "🧮 合规计算沙箱",
                "doc_catalog_inspector": "📋 制度全景探查",
                "unified_web_search": "🌐 智能外网扩展"
            }.get(selected_tool, "⚙️ 协同工具")

            thought_text = thought_inside or f"启动 [{badge_name}] 分析用户提问..."
            action_log = f"Thought: [{badge_name}] {thought_text}\nAction: {selected_tool}\nAction Input: {tool_arg}"
            action_obj = AgentActionStub(selected_tool, tool_arg, action_log)
            yield {"actions": [action_obj]}

            # 执行工具
            obs = await _execute_tool_safe(selected_tool, tool_arg)
            observations.append((selected_tool, tool_arg, obs))

            step_obj = AgentStepStub(action_obj, obs)
            yield {"steps": [step_obj]}

            # 规避死循环：若已调过规章搜索或计算器，直接进入综合收敛
            if selected_tool in ["enterprise_kb_search", "unified_web_search", "doc_catalog_inspector"]:
                break

        # 阶段三：综合收拢 (Synthesize)
        if not final_answer:
            yield {"actions": [AgentActionStub("synthesize", "", "Thought: 整合规章事实与计算结果，生成最终专业回复...")]}
            
            obs_text = "\n\n".join([f"【{t} 数据依据】:\n{o}" for t, _, o in observations])
            synth_system = (
                "你是一个严谨高效的企业本地智能知识库与业务合规助手。\n"
                "请严格基于下方获取的事实与核查依据，输出结构清晰、条理分明的最终业务解答。\n"
                "【格式准则】：\n"
                "1. 若命中本地规章，请明确引用具体规章名称（如《企业员工考勤与休假管理制度》）及对应条款要求；\n"
                "2. 若涉及计算，列出核算公式与明确结果，确保数据无误；\n"
                "3. 若引用了外网检索，请标注 [🌐 外部资讯参考] 并附带来源链接；\n"
                "4. 语言专业精炼，关键结论加粗显示。"
            )
            synth_user = f"用户提问: {question}\n\n【收集到的业务依据与核验事实】:\n{obs_text}\n\n请直接输出最终业务解答："
            
            try:
                synth_resp = await asyncio.wait_for(
                    self.target_llm.ainvoke([("system", synth_system), ("user", synth_user)]),
                    timeout=12.0
                )
                final_answer = synth_resp.content if hasattr(synth_resp, "content") else str(synth_resp)
                # 清洗可能的思考标签
                final_answer, _ = _clean_reasoning_and_get_thought(final_answer)
            except Exception as e:
                logger.error(f"综合回答生成异常: {e}")
                final_answer = "已完成规章检索与推演分析。\n\n" + obs_text

        yield {"output": final_answer}

    async def ainvoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """为非流式接口提供同步包装，返回 output 与 intermediate_steps"""
        output_text = ""
        actions = []
        steps = []
        async for chunk in self.astream(inputs):
            if "actions" in chunk:
                actions.extend(chunk["actions"])
            if "steps" in chunk:
                steps.extend(chunk["steps"])
            if "output" in chunk:
                output_text = chunk["output"]

        return {
            "output": output_text,
            "intermediate_steps": steps
        }

# ==================== 工厂方法与全局实例 ====================
def create_dynamic_agent_executor(target_llm=None):
    use_llm = target_llm or llm
    return EnterpriseAgentExecutor(use_llm)

agent_executor = create_dynamic_agent_executor(llm)

# 保持向后兼容旧变量引用
agent = agent_executor

# ==================== Session 互斥锁管理 ====================
_session_locks: Dict[str, asyncio.Lock] = {}
_SESSION_LAST_USED: Dict[str, float] = {}
_MAX_SESSIONS = 10000

def get_session_lock(session_id: str) -> asyncio.Lock:
    now = time.monotonic()
    if len(_session_locks) >= _MAX_SESSIONS:
        oldest_sids = sorted(_SESSION_LAST_USED, key=_SESSION_LAST_USED.get)[:_MAX_SESSIONS // 10]
        for sid in oldest_sids:
            _session_locks.pop(sid, None)
            _SESSION_LAST_USED.pop(sid, None)
    _SESSION_LAST_USED[session_id] = now
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]

def cleanup_session(session_id: str) -> None:
    _session_locks.pop(session_id, None)
    _SESSION_LAST_USED.pop(session_id, None)

# ==================== 会话执行包装函数 ====================
async def yunxing_agent_session(question: str, session_id: str) -> Dict[str, Any]:
    """
    负责执行多步 Agent 推理，带 Session 互斥锁、历史微压缩与 20 秒严格安全时间预算。
    彻底消灭 126 秒死锁！
    """
    lock = get_session_lock(session_id)
    async with lock:
        history = await asyncio.to_thread(huode_huibao_jiliu, session_id)
        messages = await asyncio.to_thread(lambda: history.messages)
        chat_history_str = await compact_history(messages, rewrite_llm)
        logger.info(f"[Agent] 开始处理会话 {session_id}，启动高可靠状态机推演")

        start_t = time.time()
        try:
            # 严格限制全链路总超时为 20 秒，杜绝任何长时间死锁
            async with asyncio.timeout(20.0):
                response = await agent_executor.ainvoke({
                    "input": question,
                    "chat_history": chat_history_str
                })
        except asyncio.TimeoutError:
            logger.warning(f"[Agent] 会话 {session_id} 执行触及 20 秒安全预算，启动极速降级")
            # 极速降级尝试直搜本地知识库
            fallback_res = await enterprise_kb_search.ainvoke(question)
            return {
                "answer": f"已为您快速检索本地规章库并归纳如下：\n\n{fallback_res}",
                "thought_process": [{"thought": "触发系统时间预算守护，已自动降级为本地规章极速直查", "tool": "enterprise_kb_search", "tool_input": question, "observation": "完成极速降级召回"}],
                "tools_used": ["enterprise_kb_search"]
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
        for step in intermediate_steps:
            action = step.action if hasattr(step, "action") else step[0]
            obs = step.observation if hasattr(step, "observation") else step[1]
            
            log = getattr(action, "log", "")
            thought = log
            if "Action:" in log:
                thought = log.split("Action:")[0].replace("Thought:", "").strip()
                
            thought_process.append({
                "thought": thought,
                "tool": getattr(action, "tool", "tool"),
                "tool_input": getattr(action, "tool_input", ""),
                "observation": str(obs)
            })
            
        await asyncio.to_thread(history.add_user_message, question)
        await asyncio.to_thread(history.add_ai_message, final_output)
        
        cost_time = round(time.time() - start_t, 2)
        logger.info(f"[Agent] 会话 {session_id} 顺利完成，总耗时: {cost_time}s")

        return {
            "answer": final_output,
            "thought_process": thought_process,
            "tools_used": list(set([step["tool"] for step in thought_process]))
        }
