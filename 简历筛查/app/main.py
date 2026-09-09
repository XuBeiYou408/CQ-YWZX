from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import load_config
from app.core.llm_client import get_model_status

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    try:
        status = await get_model_status(cfg)
        if status.get("local_status") == "available":
            print(f"[RecruitAI] 本地模型就绪 ({status.get('local_provider')}): {status.get('local_model')}  延迟 {status.get('local_latency_ms')}ms")
        else:
            print(f"[RecruitAI] 本地模型未检测到，云端状态: {status.get('cloud_status')}")
    except Exception as e:
        print(f"[RecruitAI] 模型探测异常: {e}")
    yield


app = FastAPI(
    title="RecruitAI",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "RecruitAI API running"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "RecruitAI"}
