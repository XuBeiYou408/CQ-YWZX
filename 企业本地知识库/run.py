# ==================== 1. 强力静音消红防御塔（必须放在最顶部） ====================
import utils.noise_suppressor # noqa: F401 — 必须在所有其他导入之前执行
import os
import sys
import shutil
import subprocess
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())  # 从脚本所在目录加载 .env，不依赖工作目录

from utils.logging_setup import setup_logging, logger
setup_logging()  # 确保构建日志在导入 app 前即可见

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
DIST_DIR = os.path.join(FRONTEND_DIR, "dist")

# ==================== 前端构建状态判断 ====================
def _need_build() -> bool:
    """dist 缺失或比前端源码旧时返回 True（避免每次启动全量构建）"""
    if not os.path.isdir(DIST_DIR) or not os.path.isfile(os.path.join(DIST_DIR, "index.html")):
        return True
    dist_mtime = os.path.getmtime(DIST_DIR)
    for name in ("index.html", "package.json", "vite.config.js"):
        p = os.path.join(FRONTEND_DIR, name)
        if os.path.exists(p) and os.path.getmtime(p) > dist_mtime:
            return True
    src_dir = os.path.join(FRONTEND_DIR, "src")
    if os.path.isdir(src_dir):
        newest = max(os.path.getmtime(os.path.join(r, f))
                     for r, _, fs in os.walk(src_dir) for f in fs)
        if newest > dist_mtime:
            return True
    return False

# ==================== 确保前端已构建 ====================
def _ensure_frontend_built():
    """确保前端已构建；构建失败不阻断后端启动（API 仍可用，首页 404）"""
    if not _need_build():
        logger.info("前端已构建，跳过构建步骤")
        return
    npm = "npm.cmd" if sys.platform == "win32" else "npm"   # Windows 上 npm 是 .cmd，需带扩展名
    if not shutil.which(npm):
        logger.warning("未找到 npm，跳过前端构建（后端 API 仍可访问，首页将 404）")
        return
    logger.info("正在构建前端，请稍候...")
    try:
        res = subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR,
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=300)
        if res.returncode == 0:
            logger.info("前端构建完成")
        else:
            logger.error(f"前端构建失败（不影响后端启动）:\n{res.stdout}\n{res.stderr}")
    except Exception as e:
        logger.error(f"前端构建异常，跳过（不影响后端启动）: {e}")

# ==================== 测试运行（取消注释以测试） ====================
# if __name__ == "__main__":
#     user_query = {'input': input("请输入问题：")}
#     print("\nAI 正在思考并回答：\n" + "-" * 40)
#     for chunk in question_answer_chain.stream(user_query):
#         print(chunk, end="", flush=True)
#     print("\n" + "-" * 40)

# ==================== FastAPI 服务化启动 ====================
if __name__ == "__main__":
    import uvicorn
    _ensure_frontend_built()          # 先构建前端，再导入 app（app 挂载 dist）
    from app.main import app
    uvicorn.run(app, host="0.0.0.0", port=8010)
