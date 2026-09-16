import os
import time
import logging
import asyncio
from typing import Dict, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from utils.logging_setup import setup_logging
from app.schemas import APIResponse
from config import API_KEYS, AUTH_ENABLED

# 统一初始化安全结构化日志
setup_logging()
logger = logging.getLogger(__name__)

# IP 速率限制数据结构与有界清理
_RATE_BUCKET: Dict[str, List[float]] = {}
RATE_LIMIT_MAX = 30
RATE_LIMIT_WINDOW = 60
_MAX_TRACKED_IPS = 10000                     # 限流桶有界上限
_RATE_CLEANUP_INTERVAL = 600.0               # 清理周期（秒）
_last_cleanup_ts = 0.0

# R2-C3 修复：FastAPI 启动预热生命周期，防止首次异步请求在主 Event Loop 中阻塞加载
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("正在执行应用启动预热任务...")
    try:
        from rag.retriever import get_retrievers
        await asyncio.to_thread(get_retrievers)
        logger.info("向量数据库与混合检索器后端预热加载完成！")
    except Exception as e:
        logger.warning(f"应用启动预热遇到异常: {e}")
        
    if not API_KEYS and not AUTH_ENABLED:
        logger.warning("未配置 API_KEYS 且未开启 AUTH_ENABLED，服务以开放模式运行。生产环境请配置 API_KEYS。")
    yield
    logger.info("正在关闭应用...")

app = FastAPI(
    title="企业级自适应问答 Agent 系统",
    description="基于 LangChain + DeepSeek + FAISS + ReAct Agent + 混合检索的高可用企业知识库系统",
    version="2.1",
    lifespan=lifespan
)

# 修复 A & G：重构 API 鉴权与有界 IP 频率控制中间件（前瞻性加入 SPA 首页豁免）
@app.middleware("http")
async def auth_and_rate_limit_middleware(request: Request, call_next):
    global _last_cleanup_ts
    path = request.url.path
    
    # 修复 G：豁免开放端点（健康检查、前端静态文件及 SPA 网页入口）
    _OPEN_PATHS = ("/", "/index.html", "/favicon.ico")
    if path.startswith("/health") or path.startswith("/assets") or path in _OPEN_PATHS:
        response = await call_next(request)
        if path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # 1) 鉴权：显式开启 或 已配置 Key → 强制校验；显式开启但缺 Key → fail-closed
    if AUTH_ENABLED:
        if not API_KEYS:
            logger.error("AUTH_ENABLED=true 但未配置 API_KEYS，拒绝所有请求")
            return JSONResponse(
                status_code=503,
                content=APIResponse(code=503, message="服务鉴权配置缺失").model_dump()
            )
    if AUTH_ENABLED or API_KEYS:
        key = request.headers.get("X-API-Key", "")
        if not key or key not in API_KEYS:
            return JSONResponse(
                status_code=401,
                content=APIResponse(code=401, message="未经授权的访问：无效或缺失 API Key").model_dump()
            )

    # 2) IP 令牌桶限流
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = [t for t in _RATE_BUCKET.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
    if len(bucket) >= RATE_LIMIT_MAX:
        return JSONResponse(
            status_code=429,
            content=APIResponse(code=429, message="请求过于频繁，触发限流保护，请稍后再试").model_dump()
        )
    bucket.append(now)
    _RATE_BUCKET[ip] = bucket

    # 3) 周期清理窗口外无活动的 IP，防止内存无限膨胀
    if len(_RATE_BUCKET) > _MAX_TRACKED_IPS and now - _last_cleanup_ts > _RATE_CLEANUP_INTERVAL:
        _last_cleanup_ts = now
        cutoff = now - RATE_LIMIT_WINDOW * 10
        stale = [k for k, v in _RATE_BUCKET.items() if not v or v[-1] < cutoff]
        for k in stale:
            _RATE_BUCKET.pop(k, None)

    return await call_next(request)

# 项目 1 修复：全局异常脱敏处理，防止敏感堆栈与数据库细节泄露给前端
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局未捕获异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=APIResponse(code=500, message="服务器内部异常，请稍后重试").model_dump()
    )

from app.routes.ask import router as ask_router
from app.routes.documents import router as documents_router
app.include_router(ask_router)
app.include_router(documents_router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
