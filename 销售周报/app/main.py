"""
SalesAgent · 企业销售周报自动汇总智能体服务入口
端口: 8040
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import load_config
from app.core.llm_client import get_model_status

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    print("=" * 60)
    print(" 🚀 SalesAgent · 企业销售周报自动汇总智能体正在启动...")
    print(" 📍 服务端口: 8040 | 访问地址: http://127.0.0.1:8040")
    print("=" * 60)
    try:
        status = await get_model_status(cfg)
        if status.get("local_status") == "available":
            print(f" [SalesAgent] 本地大模型已就绪 ({status.get('local_provider')}): {status.get('local_model')} 延迟 {status.get('local_latency_ms')}ms")
        else:
            print(f" [SalesAgent] 本地模型未探活，云端状态: {status.get('cloud_status')}")
    except Exception as e:
        print(f" [SalesAgent] 模型探活提示: {e}")
    yield
    print(" [SalesAgent] 服务已停止。")


app = FastAPI(
    title="SalesAgent · 销售周报自动汇总智能体",
    version="1.0.0",
    description="对企业内部销售人员提交的销售周报，进行自动本地汇总，便于销售主管查看、统计与战略决策。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "SalesAgent API Running. Please place index.html in static/"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "SalesAgent", "port": 8040}