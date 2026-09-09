import copy
import json
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"
UPLOAD_DIR = BASE_DIR / "uploads"

# ????????
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8030,
    },
    "active_provider": "local",
    "local_model": {
        "lm_studio_url": "http://127.0.0.1:1234/v1",
        "ollama_url": "http://127.0.0.1:11434/v1",
        "model_name": "qwen3.8-27b",
        "timeout": 45,
    },
    "cloud_model": {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model_name": "deepseek-chat",
        "timeout": 45,
    },
}

CLOUD_PRESETS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "name": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "dashscope": {
        "name": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo"],
    },
    "moonshot": {
        "name": "moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k"],
    },
    "custom": {
        "name": "custom",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o"],
    },
}


def _deep_merge(default: Dict[str, Any], custom: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(default)
    for k, v in custom.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def load_config() -> Dict[str, Any]:
    """?? config.json?????????????????"""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            custom_cfg = json.load(f)
        if not isinstance(custom_cfg, dict):
            custom_cfg = {}
    except Exception:
        custom_cfg = {}

    merged_cfg = _deep_merge(DEFAULT_CONFIG, custom_cfg)
    return merged_cfg


def save_config(cfg: Dict[str, Any]) -> None:
    """?? config.json"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
