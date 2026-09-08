"""
智审 (Doc-Agent) - 一键服务启动脚本
"""
import os
import sys
import time
import threading
import webbrowser
import uvicorn
from config import config

# 确保以当前文件所在目录为工作基准
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BANNER = """
=============================================================================
  合同审查 AGENT · 企业级合同合规智能审查系统
  -------------------------------------------------------------
  * 推理服务: 本地端侧大模型 (http://127.0.0.1:1234/v1)
  * 服务地址: http://localhost:8020 (将自动为您弹出浏览器)
=============================================================================
"""

def auto_open_browser(url: str, delay: float = 1.2):
    """后台延迟自动唤起系统默认浏览器，确保服务端口已完全就绪"""
    time.sleep(delay)
    try:
        print(f"\n>> [系统] 正在自动为您打开浏览器: {url} ...")
        webbrowser.open_new_tab(url)
    except Exception as e:
        print(f">> 自动打开浏览器失败，请手动访问: {url} ({e})")

def main():
    print(BANNER.strip())
    url = f"http://localhost:{config.PORT}"
    print(f">> 正在启动智审服务，监听端口: {config.PORT} ...")
    print(f">> 访问网址: {url}")
    print(">> 提示：请确保已在 LM Studio 中加载模型并开启 Local Server。")
    print("-" * 77)

    # 启动后台自动打开浏览器线程
    threading.Thread(target=auto_open_browser, args=(url, 1.2), daemon=True).start()

    # 启动后台服务
    uvicorn.run(
        "app.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    main()
