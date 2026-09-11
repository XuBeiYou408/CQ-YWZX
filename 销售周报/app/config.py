"""
全局配置管理模块 - 销售周报自动汇总智能体
"""
import json
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"
UPLOAD_DIR = BASE_DIR / "uploads"
EXPORT_DIR = BASE_DIR / "exports"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8040,
    },
    "active_provider": "local",  # local | cloud
    "local_model": {
        "lm_studio_url": "http://127.0.0.1:1234/v1",
        "ollama_url": "http://127.0.0.1:11434/v1",
        "model_name": "qwen3.8-27b",
        "timeout": 240,  # 端侧推理模型生成完整内参实测约 2-3 分钟，留足余量
    },
    "cloud_model": {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model_name": "deepseek-chat",
        "timeout": 60,
    },
}

CLOUD_PRESETS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
    },
    "dashscope": {
        "name": "通义千问 (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo"],
        "default_model": "qwen-plus",
    },
    "moonshot": {
        "name": "月之暗面 (Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k"],
        "default_model": "moonshot-v1-8k",
    },
    "custom": {
        "name": "自定义 OpenAI 兼容接口",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o"],
        "default_model": "gpt-4o-mini",
    },
}


def _deep_merge(base: dict, update: dict) -> dict:
    merged = dict(base)
    for k, v in update.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, data)
    except Exception as exc:
        print(f"[SalesAgent] 配置文件读取失败，已回退默认配置: {exc}")
        return DEFAULT_CONFIG.copy()


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存配置异常: {e}")