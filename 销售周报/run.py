# -*- coding: utf-8 -*-
"""
SalesAgent · 企业销售周报自动汇总智能体 一键启动程序
自动自检 8040 端口、探测本地 LM Studio / Ollama 大模型服务、拉起服务并自动唤起浏览器
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# 确保在 Windows 控制台下不发生编码崩溃
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

HOST = '127.0.0.1'
PORT = 8040


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def check_local_model() -> tuple[str, str]:
    """检查本地模型连通性"""
    try:
        req = urllib.request.Request('http://127.0.0.1:1234/v1/models', headers={'User-Agent': 'SalesAgent-Runner'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                models = data.get('data', [])
                model_name = models[0]['id'] if models else 'qwen3.8-27b'
                return 'lm_studio', model_name
    except Exception:
        pass

    try:
        req = urllib.request.Request('http://127.0.0.1:11434/v1/models', headers={'User-Agent': 'SalesAgent-Runner'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                models = data.get('data', [])
                model_name = models[0]['id'] if models else 'ollama'
                return 'ollama', model_name
    except Exception:
        pass

    return 'none', ''


def open_browser():
    time.sleep(1.2)
    url = f'http://{HOST}:{PORT}'
    print(f' 🌐 正在自动唤起浏览器: {url}')
    webbrowser.open(url)


def main():
    print("=" * 66)
    print("  📊 SalesAgent · 企业销售周报自动汇总智能体")
    print("=" * 66)

    # 1. 端口检查
    if is_port_in_use(PORT):
        print(f" [警告] 端口 {PORT} 已被占用，服务可能已在后台运行。")
        print(f" 直接尝试访问: http://{HOST}:{PORT}")
        webbrowser.open(f'http://{HOST}:{PORT}')
        return

    # 2. 检查本地模型
    print(" [1/3] 正在探测本地大模型推理引擎...")
    provider, model_name = check_local_model()
    if provider == 'lm_studio':
        print(f"   ✅ 检测到 LM Studio 运行中 (127.0.0.1:1234) | 模型: {model_name}")
    elif provider == 'ollama':
        print(f"   ✅ 检测到 Ollama 运行中 (127.0.0.1:11434) | 模型: {model_name}")
    else:
        print("   ⚠️  未检测到本地 LM Studio，系统将启用高保真预设内参并支持界面切换云端模型。")

    # 3. 异步启动浏览器
    threading.Thread(target=open_browser, daemon=True).start()

    # 4. 启动 uvicorn
    print(f" [2/3] 正在启动 SalesAgent Web 驾驶舱: http://{HOST}:{PORT}")
    print(" [3/3] 按 Ctrl+C 可停止服务\n")

    import uvicorn
    from app.main import app
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == '__main__':
    main()