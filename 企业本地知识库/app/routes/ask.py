import time
import os
import re
import json
import logging
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas import QueryRequest, AgentQueryRequest, APIResponse, valid_session_id
from rag.chain import question_answer_chain, create_qa_chain
from rag.agent import yunxing_agent_session, agent_executor, create_dynamic_agent_executor, get_session_lock, cleanup_session
from rag.memory import huode_huibao_jiliu, qingkong_huibao_jiliu, compact_history
from rag.router import xitong_luyou
from rag.llm import rewrite_llm, huode_dongtai_llm
from config import LOCAL_DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter()

def _sanitize(text: str, limit: int = 200) -> str:
    """项目 9 修复：对日志输出的用户输入进行脱敏与换行单行化处理，防止日志注入与泄露"""
    clean_str = re.sub(r"[\r\n\t]", " ", text or "")
    return clean_str[:limit]

def _sse(obj) -> str:
    """问题 I 修复：序列化 SSE 数据帧，转义 JSON 内部换行，避免破坏 SSE 协议帧边界"""
    return json.dumps(obj, ensure_ascii=False).replace("\n", "\\n")

# ==================== 健康检查与本地模型检测 ====================
@router.get("/health", response_model=APIResponse)
def health():
    return APIResponse(data={"status": "ok"})

@router.get("/models/local", response_model=APIResponse)
@router.get("/api/models/local", response_model=APIResponse)
async def get_local_models():
    """
    检查本地大模型服务 (优先探测 LM Studio: 1234 端口，兼容 11434 端口) 并动态返回模型列表
    """
    import urllib.request
    # 1. 优先探测 LM Studio (http://127.0.0.1:1234/v1/models)
    try:
        req = urllib.request.Request("http://127.0.0.1:1234/v1/models", headers={"User-Agent": "FastAPI"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [
                    m.get("id") for m in data.get("data", [])
                    if m.get("id") and "embed" not in m.get("id", "").lower()
                ]
                return APIResponse(data={
                    "status": "connected",
                    "url": "http://127.0.0.1:1234/v1",
                    "service": "LM Studio",
                    "models": models
                })
    except Exception as e:
        logger.debug(f"LM Studio 服务未检测到: {str(e)}")

    # 2. 兼容探测其他本地服务 (11434 端口)
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "FastAPI"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                return APIResponse(data={
                    "status": "connected",
                    "url": "http://127.0.0.1:11434/v1",
                    "service": "Local LLM",
                    "models": models
                })
    except Exception:
        pass
        
    return APIResponse(data={
        "status": "disconnected",
        "url": "http://127.0.0.1:1234/v1",
        "service": "LM Studio",
        "models": ["qwen3.8-27b", "minimax-h3_ggufs", "deepseek-v4-flash-0731", "qwen2.5:7b"]
    })

# ==================== 普通问答接口 (T13: 响应结构规范化) ====================
@router.post("/ask", response_model=APIResponse)
async def ask(req: QueryRequest):
    start_time = time.time()
    try:
        logger.info(f"收到同步问答提问: {_sanitize(req.question)}, 模式: {req.provider}, 模型: {req.model_name}")
        dyn_llm = huode_dongtai_llm(req.provider, req.model_name, streaming=False, api_key=req.api_key, base_url=req.api_base)
        dyn_qa_chain = create_qa_chain(dyn_llm, req.provider, req.model_name)
        result = await dyn_qa_chain.ainvoke({
            "input": req.question
        })
        cost = round(time.time() - start_time, 2)
        logger.info(f"问答响应完成，耗时: {cost}s")
        return APIResponse(data={
            "answer": result,
            "cost_time": cost
        })
    except Exception as e:
        err_text = str(e)
        logger.error(f"问答接口发生异常: {err_text}", exc_info=True)
        cost = round(time.time() - start_time, 2)
        if "1234" in err_text or "11434" in err_text or "Connection refused" in err_text or "ConnectError" in err_text:
            return APIResponse(data={
                "answer": "⚠️ **无法连接到本地大模型服务 (http://127.0.0.1:1234)**\n\n请排查：\n1. 请确认本地 LM Studio（或本地推理服务）已启动并开启 Local Server；\n2. 若暂无本地模型环境，请前往【⚙️ 设置】页面切换为【☁️ 云端 API 模式】。",
                "cost_time": cost
            })
        elif "api_key" in err_text.lower() or "401" in err_text or "authentication" in err_text.lower():
            return APIResponse(data={
                "answer": "⚠️ **云端 API 认证失败**：请前往【⚙️ 设置】页面配置有效的 API Key，或在项目根目录 `.env` 中配置 `DEEPSEEK_API_KEY`。",
                "cost_time": cost
            })
        return APIResponse(data={
            "answer": f"⚠️ **调用异常**：{err_text}",
            "cost_time": cost
        })

# ==================== 统一 SSE 流式分流接口 (T12) ====================
@router.post("/stream")
async def stream(req: AgentQueryRequest):
    """
    统一 SSE 流式入口：基于轻量路由分类自动分流
    - simple_rag: 走知识库快车道直出
    - agent: 走 ReAct Agent 推理链慢车道
    - summarize: 走摘要扩展通道
    """
    async def generate():
        logger.info(f"收到统一 SSE 流式请求: '{_sanitize(req.question)}', 会话ID: {req.session_id}, 模式: {req.provider}, 模型: {req.model_name}")
        
        try:
            # 实例化前端选择的端/云 LLM 实例
            dyn_stream_llm = huode_dongtai_llm(req.provider, req.model_name, streaming=True, api_key=req.api_key, base_url=req.api_base)
            dyn_rewrite_llm = huode_dongtai_llm(req.provider, req.model_name, streaming=False, api_key=req.api_key, base_url=req.api_base)
            dyn_qa_chain = create_qa_chain(dyn_stream_llm, req.provider, req.model_name)
            dyn_agent_executor = create_dynamic_agent_executor(dyn_stream_llm)

            # 1. 意图分流
            intent = await xitong_luyou(req.question, dyn_rewrite_llm)
            yield f"data: {_sse({'type': 'route', 'intent': intent})}\n\n"
            
            if intent == "system_meta":
                prov_label = "🏠 本地端侧硬件部署" if req.provider == "local" else "☁️ 云端 API"
                fast_meta_resp = f"我是运行在 **[{prov_label}]** 环境下的 **{req.model_name}** 大语言模型！结合企业本地知识库与端侧算力协同为您提供业务合规智能支持。"
                yield f"data: {_sse({'type': 'content', 'content': fast_meta_resp})}\n\n"
            elif intent == "simple_rag":
                output_has_content = False
                async for chunk in dyn_qa_chain.astream({"input": req.question}):
                    if chunk:
                        output_has_content = True
                        yield f"data: {_sse({'type': 'content', 'content': chunk})}\n\n"
                if not output_has_content:
                    # 降级退回由包含丰富知识库的 Agent 兜底回答
                    async for chunk in dyn_stream_llm.astream(req.question):
                        yield f"data: {_sse({'type': 'content', 'content': chunk.content})}\n\n"
            else:
                lock = get_session_lock(req.session_id)
                async with lock:
                    history = await asyncio.to_thread(huode_huibao_jiliu, req.session_id)
                    messages = await asyncio.to_thread(lambda: history.messages)
                    chat_history_str = await compact_history(messages, dyn_rewrite_llm)
                    
                    final_output = ""
                    async for chunk in dyn_agent_executor.astream({
                        "input": req.question,
                        "chat_history": chat_history_str
                    }):
                        if "actions" in chunk:
                            for action in chunk["actions"]:
                                yield f"data: {_sse({'type': 'thought', 'content': action.log})}\n\n"
                        elif "steps" in chunk:
                            for step in chunk["steps"]:
                                yield f"data: {_sse({'type': 'observation', 'content': str(step.observation)})}\n\n"
                        elif "output" in chunk:
                            final_output = chunk["output"]
                            if "Agent stopped due to iteration limit" in final_output or "time limit" in final_output:
                                final_output = "已为您完成知识库深度检索与分析。"
                            yield f"data: {_sse({'type': 'output', 'content': final_output})}\n\n"
                            
                    if final_output:
                        await asyncio.to_thread(history.add_user_message, req.question)
                        await asyncio.to_thread(history.add_ai_message, final_output)
        except Exception as e:
            err_text = str(e)
            logger.error(f"SSE 流式生成异常: {err_text}", exc_info=True)
            if "1234" in err_text or "11434" in err_text or "Connection refused" in err_text or "ConnectError" in err_text:
                friendly_msg = (
                    "⚠️ **无法连接到本地大模型服务 (http://127.0.0.1:1234)**\n\n"
                    "**排查指引：**\n"
                    "1. 本地大模型依赖 LM Studio 或本地推理引擎。请在 LM Studio 中确认已启动 Local Server 并加载模型；\n"
                    "2. 若当前电脑未开启本地模型服务，请前往顶部导航栏 **【⚙️ 设置】**，一键切换为 **【☁️ 云端 API 模式】** 即可直接体验！"
                )
            elif "api_key" in err_text.lower() or "authentication" in err_text.lower() or "401" in err_text:
                friendly_msg = (
                    "⚠️ **大模型 API 认证失败**\n\n"
                    "未配置有效的 API 密钥。请前往 **【⚙️ 设置】** 页面填入您的 API Key，或在项目根目录 `.env` 文件中配置 `DEEPSEEK_API_KEY`。"
                )
            else:
                friendly_msg = f"⚠️ **生成回答时发生异常**：{err_text}\n\n建议检查网络连接或前往 **【⚙️ 设置】** 切换模型重试。"
            yield f"data: {_sse({'type': 'content', 'content': friendly_msg})}\n\n"
        finally:
            yield f"data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

# ==================== 评估结果接口 ====================
@router.get("/evaluation/results", response_model=APIResponse)
def get_evaluation_results():
    path = os.path.join(LOCAL_DB_PATH, "evaluation_results.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="评估结果不存在，请先运行评估")
    with open(path, "r", encoding="utf-8") as f:
        return APIResponse(data=json.load(f))

@router.get("/evaluation/dataset", response_model=APIResponse)
def get_dataset_info():
    path = os.path.join(LOCAL_DB_PATH, "golden_dataset.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="测试集不存在")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return APIResponse(data={"count": len(data), "exists": True})

# ==================== Agent 智能问答接口 ====================
@router.post("/agent/ask", response_model=APIResponse)
async def agent_ask(req: AgentQueryRequest):
    start_time = time.time()
    try:
        logger.info(f"收到 Agent 同步请求: '{_sanitize(req.question)}', 会话ID: {req.session_id}")
        result = await yunxing_agent_session(req.question, req.session_id)
        cost = round(time.time() - start_time, 2)
        return APIResponse(data={
            "answer": result["answer"],
            "thought_process": result["thought_process"],
            "tools_used": result["tools_used"],
            "cost_time": cost
        })
    except Exception as e:
        logger.error(f"Agent 接口错误: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="服务内部错误，请稍后重试")

# ==================== Agent SSE 流式接口兼容别名 ====================
@router.post("/agent/stream")
async def agent_stream(req: AgentQueryRequest):
    return await stream(req)

# ==================== 清理会话记忆接口 ====================
@router.delete("/agent/memory/{session_id}", response_model=APIResponse)
def delete_memory(session_id: str):
    # 修复 C: 路径参数校验 valid_session_id
    if not valid_session_id(session_id):
        raise HTTPException(status_code=400, detail="无效的会话标识")
    success = qingkong_huibao_jiliu(session_id)
    if success:
        cleanup_session(session_id)
        return APIResponse(data={"status": "ok", "message": f"会话 {session_id} 记忆及锁资源已成功清空"})
    raise HTTPException(status_code=500, detail="清空记忆失败")