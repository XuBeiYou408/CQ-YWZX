# -*- coding: utf-8 -*-
"""
RecruitAI · 智能招聘与简历初筛智能体 一键启动程序
自动自检端口、探测本地/云端大模型服务、启动 HTTP 服务并自动打开浏览器
"""
import os
import sys
import time
import socket
import webbrowser
import threading
import urllib.request
import json
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

HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '8030'))

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0

def check_local_model() -> tuple[str, str]:
    """检查本地模型连通性"""
    try:
        req = urllib.request.Request('http://127.0.0.1:1234/v1/models', headers={'User-Agent': 'RecruitAI-Runner'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                models = data.get('data', [])
                model_name = models[0]['id'] if models else 'qwen3.8-27b'
                return 'lm_studio', model_name
    except Exception:
        pass

    try:
        req = urllib.request.Request('http://127.0.0.1:11434/v1/models', headers={'User-Agent': 'RecruitAI-Runner'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                models = data.get('data', [])
                model_name = models[0]['id'] if models else 'ollama'
                return 'ollama', model_name
    except Exception:
        pass

    return 'none', ''

def open_browser(url: str):
    time.sleep(1.2)
    print(f'[*] 正在自动拉起默认浏览器访问工作台: {url}')
    try:
        webbrowser.open(url)
    except Exception:
        print(f'[!] 自动打开浏览器失败，请手动在浏览器访问: {url}')

def main():
    print('=' * 65)
    print('   RecruitAI · 企业智能招聘与简历初筛工作台 (Stitch 1:1 纯端侧版)')
    print('   项目架构: 方案一 (轻量化纯端侧自主构建 - 零Docker/零云依赖)')
    print('=' * 65)

    provider, model_name = check_local_model()
    if provider == 'lm_studio':
        print(f'[*] [OK] 本地 LM Studio 推理服务已就绪！')
        print(f'    底座模型: {model_name} (端口 1234)')
    elif provider == 'ollama':
        print(f'[*] [OK] 本地 Ollama 推理服务已就绪！')
        print(f'    底座模型: {model_name} (端口 11434)')
    else:
        print('[!] [!] 未检测到本地 LM Studio / Ollama。')
        print('    (您可以在工作台右上角点击模型胶囊，随时无缝接入 DeepSeek / 通义千问 / Kimi)')

    if is_port_in_use(PORT):
        print(f'[!] 警告: 端口 {PORT} 已被占用，可能已有一个实例正在运行。')
        print(f'    请直接在浏览器中打开: http://{HOST}:{PORT}')
        sys.exit(1)

    url = f'http://{HOST}:{PORT}'
    print(f'[*] 正在启动 FastAPI 服务...')
    print(f'[*] 访问地址: {url}')
    print('=' * 65)

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    import uvicorn
    uvicorn.run('app.main:app', host=HOST, port=PORT, log_level='info')

if __name__ == '__main__':
    main()
