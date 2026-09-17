# -*- coding: utf-8 -*-
"""
智审 (Doc-Agent) · 模型管理模块
======================================================================
职责：持久化"审查用哪个模型"的用户配置，并向引擎/接口提供**当前生效值**。

设计要点
----------------------------------------------------------------------
1. 两个服务类型：
   - `local`：本机 LM Studio（OpenAI 兼容端点，默认 127.0.0.1:1234/v1）
   - `cloud`：任意 OpenAI 兼容云端 API（内置 DeepSeek / Kimi / 通义 / 智谱 / 自定义）
2. 配置文件 `model_config.json` 放在项目根目录，**已在 .gitignore 中排除**
   （公开仓库绝不能提交 API Key）。文件权限尽力收紧为 600。
3. **密钥绝不回显**：对外只返回 `has_key` 与掩码（`masked_view()`），
   明文仅在进程内部使用；云端 api_key 为空时回退到预设对应的环境变量。
4. 任何异常都不阻断审查主流程：读取失败回退内置默认值（本地 gemma）。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from config import config

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)  # contract/ -> 项目根
CONFIG_PATH = os.path.join(PROJECT_ROOT, "model_config.json")

PROVIDER_LOCAL = "local"
PROVIDER_CLOUD = "cloud"

# 云端预设（均为 OpenAI 兼容端点；models 仅作下拉建议，允许手填）
CLOUD_PRESETS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "label": "DeepSeek 官方",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "env_key": "DEEPSEEK_API_KEY",
        "doc": "https://platform.deepseek.com",
    },
    "kimi": {
        "label": "Kimi / Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "env_key": "MOONSHOT_API_KEY",
        "doc": "https://platform.moonshot.cn",
    },
    "qwen": {
        "label": "通义千问（DashScope 兼容模式）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo"],
        "env_key": "DASHSCOPE_API_KEY",
        "doc": "https://bailian.console.aliyun.com",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4-plus", "glm-4-long"],
        "env_key": "ZHIPU_API_KEY",
        "doc": "https://open.bigmodel.cn",
    },
    "custom": {
        "label": "自定义（任意 OpenAI 兼容端点）",
        "base_url": "",
        "models": [],
        "env_key": "OPENAI_API_KEY",
        "doc": "",
    },
}

# 用可重入锁：save() 内部会在持锁状态下间接调用 load()/get_effective()，
# 若用普通 Lock 会自锁死（本模块曾被这个 bug 卡住整个进程，务必保持 RLock）。
_lock = threading.RLock()


def _defaults() -> Dict[str, Any]:
    """内置默认：本地 LM Studio + 端侧主力模型（保持开箱即用行为不变）"""
    local_model = config.AGENT_MODEL or config.DEFAULT_MODEL or "google/gemma-4-e4b"
    return {
        "provider": PROVIDER_LOCAL,
        "local": {
            "base_url": config.LM_STUDIO_BASE_URL or "http://127.0.0.1:1234/v1",
            "api_key": config.LM_STUDIO_API_KEY or "lm-studio",
            "model": local_model,
        },
        "cloud": {
            "preset": "deepseek",
            "base_url": CLOUD_PRESETS["deepseek"]["base_url"],
            "api_key": "",
            "model": CLOUD_PRESETS["deepseek"]["models"][0],
        },
    }


def _merge_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    """把磁盘上的配置与默认值合并，容忍缺字段/坏字段（版本演进安全）"""
    merged = _defaults()
    if not isinstance(data, dict):
        return merged
    provider = str(data.get("provider") or merged["provider"]).lower()
    merged["provider"] = provider if provider in (PROVIDER_LOCAL, PROVIDER_CLOUD) else PROVIDER_LOCAL
    for section in ("local", "cloud"):
        raw = data.get(section)
        if isinstance(raw, dict):
            for k in ("base_url", "api_key", "model", "preset"):
                if k in raw and raw[k] is not None:
                    merged[section][k] = str(raw[k]).strip()
    if not merged["local"]["base_url"]:
        merged["local"]["base_url"] = config.LM_STUDIO_BASE_URL or "http://127.0.0.1:1234/v1"
    if not merged["cloud"]["base_url"]:
        preset = CLOUD_PRESETS.get(merged["cloud"].get("preset") or "deepseek") or CLOUD_PRESETS["deepseek"]
        merged["cloud"]["base_url"] = preset["base_url"]
    return merged


def load() -> Dict[str, Any]:
    """读取配置（带默认值合并）；文件不存在或损坏时返回默认配置"""
    with _lock:
        if not os.path.exists(CONFIG_PATH):
            return _defaults()
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return _merge_defaults(json.load(f))
        except Exception as e:
            logger.warning(f"读取 model_config.json 失败（回退默认配置）: {e}")
            return _defaults()


def save(new_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """合并并落盘；返回保存后的完整配置（含明文，仅供进程内部使用）"""
    with _lock:
        current = _defaults()
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    current = _merge_defaults(json.load(f))
            except Exception:
                pass
        if isinstance(new_cfg, dict):
            if str(new_cfg.get("provider") or "").lower() in (PROVIDER_LOCAL, PROVIDER_CLOUD):
                current["provider"] = str(new_cfg["provider"]).lower()
            for section in ("local", "cloud"):
                raw = new_cfg.get(section)
                if isinstance(raw, dict):
                    for k in ("base_url", "api_key", "model", "preset"):
                        if k in raw and raw[k] is not None:
                            val = str(raw[k]).strip()
                            # 空字符串视为"不改动"仅对密钥成立（避免误清空）
                            if k == "api_key" and val == "":
                                continue
                            current[section][k] = val
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except Exception:
            pass

    # 注意：日志写在锁外——get_effective() 内部会再次取锁/读文件，
    # 放在锁内既容易自锁，也会让写盘时序变复杂。
    try:
        eff = get_effective()
        logger.info(f"模型配置已更新: provider={current['provider']} 生效模型={eff['model']}")
    except Exception as e:
        logger.debug(f"模型配置日志记录失败（不影响保存）: {e}")
    return current


def resolve_cloud_key(cloud: Dict[str, Any]) -> str:
    """云端密钥：优先用户填写的，其次对应预设的环境变量"""
    key = (cloud.get("api_key") or "").strip()
    if key:
        return key
    preset = CLOUD_PRESETS.get(cloud.get("preset") or "") or {}
    env_key = preset.get("env_key")
    if env_key:
        return (os.getenv(env_key) or "").strip()
    return ""


# 兼容旧内部命名
_resolve_cloud_key = resolve_cloud_key


def get_effective() -> Dict[str, Any]:
    """返回**当前生效**的连接参数：{provider, base_url, api_key, model, is_local}"""
    cfg = load()
    provider = cfg["provider"]
    if provider == PROVIDER_CLOUD:
        cloud = cfg["cloud"]
        return {
            "provider": PROVIDER_CLOUD,
            "base_url": cloud.get("base_url") or CLOUD_PRESETS["deepseek"]["base_url"],
            "api_key": _resolve_cloud_key(cloud) or "sk-missing",
            "model": cloud.get("model") or "deepseek-chat",
            "is_local": False,
        }
    local = cfg["local"]
    return {
        "provider": PROVIDER_LOCAL,
        "base_url": local.get("base_url") or "http://127.0.0.1:1234/v1",
        "api_key": local.get("api_key") or "lm-studio",
        "model": local.get("model") or (config.AGENT_MODEL or config.DEFAULT_MODEL),
        "is_local": True,
    }


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * 6}{secret[-4:]}"


def masked_view() -> Dict[str, Any]:
    """对外安全视图：密钥只给 has_key + 掩码，绝不下发明文"""
    cfg = load()
    eff = get_effective()
    cloud = cfg["cloud"]
    local = cfg["local"]
    cloud_key = _resolve_cloud_key(cloud)
    return {
        "provider": cfg["provider"],
        "local": {
            "base_url": local.get("base_url", ""),
            "model": local.get("model", ""),
            # model_is_auto=True 表示用户未指定本地模型，审查时走"跟随会话/已加载模型"自动优选
            "model_is_auto": not (local.get("model") or "").strip(),
            "has_key": bool(local.get("api_key")),
            "key_masked": _mask(local.get("api_key", "")),
        },
        "cloud": {
            "preset": cloud.get("preset", "deepseek"),
            "base_url": cloud.get("base_url", ""),
            "model": cloud.get("model", ""),
            "has_key": bool(cloud_key),
            "key_masked": _mask(cloud_key),
            "key_from_env": (not (cloud.get("api_key") or "").strip()) and bool(cloud_key),
        },
        "effective": {
            "provider": eff["provider"],
            "base_url": eff["base_url"],
            "model": eff["model"],
            "is_local": eff["is_local"],
        },
        "presets": [
            {
                "id": pid,
                "label": p["label"],
                "base_url": p["base_url"],
                "models": p["models"],
                "env_key": p["env_key"],
                "doc": p.get("doc", ""),
            }
            for pid, p in CLOUD_PRESETS.items()
        ],
    }
