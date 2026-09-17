"""
智审 (Doc-Agent) - FastAPI 主应用程序
挂载 API 路由与前端静态单页应用
"""
import os
import urllib.request
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.schemas import APIResponse
from app.routes.contract import router as contract_router
from app.routes.model_admin import router as model_admin_router
from config import config

app = FastAPI(
    title="智审 Doc-Agent · 企业离线合同合规智能审查系统",
    description="基于 Intel Core Ultra 7 与 LM Studio 本地端侧算力构建的商业级合同审查智能体；审查模型可在界面「模型管理」面板切换为本地 LM Studio 或云端 API（选云端时合同文本经网络发往所选服务商）",
    version="1.0.0"
)

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 API 路由
app.include_router(contract_router, prefix="/api/contract", tags=["合同审查"])
app.include_router(model_admin_router, prefix="/api/model", tags=["模型管理"])

@app.get("/health", response_model=APIResponse)
def health():
    return APIResponse(data={
        "status": "ok",
        "platform": config.PLATFORM_TAG
    })

@app.get("/api/lmstudio/status", response_model=APIResponse)
def get_lmstudio_status():
    """实时检测 LM Studio 在线状态与当前模型列表"""
    try:
        req = urllib.request.Request(f"{config.LM_STUDIO_BASE_URL}/models")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("id") for m in data.get("data", [])]
                return APIResponse(data={
                    "connected": True,
                    "url": config.LM_STUDIO_BASE_URL,
                    "models": models,
                    "active_model": models[0] if models else config.DEFAULT_MODEL
                })
    except Exception as e:
        pass
    
    return APIResponse(data={
        "connected": False,
        "url": config.LM_STUDIO_BASE_URL,
        "models": [],
        "active_model": None
    })

# 挂载前端单页静态应用
frontend_dist_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")

if os.path.exists(frontend_dist_dir):
    app.mount("/static", StaticFiles(directory=frontend_dist_dir), name="static")
    
    @app.get("/")
    def index():
        return FileResponse(os.path.join(frontend_dist_dir, "index.html"))
