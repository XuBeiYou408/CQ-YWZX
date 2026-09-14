# -*- coding: utf-8 -*-
"""会话模型解析：让「审查用的模型」跟随「当前 WorkBuddy 会话正在用的模型」。

======================================================================
为什么需要这个模块
======================================================================
WorkBuddy 里有**两套互不相干的模型**：
  1. 对话模型 —— 用户在客户端下拉里选的（可能是云端 deepseek/hy3，也可能是本地 LM Studio）；
  2. 工具内部推理模型 —— 本项目（MCP 工具）自己调用的模型。

用户期望「我选什么模型，审查就用什么模型」。要做到这点，工具必须先知道
「当前这个会话在用哪个模型」——本模块负责回答这个问题，并把它映射为一个
**可直达的 OpenAI 兼容后端**（端点 + 密钥 + 模型名）。

======================================================================
数据来源（全部只读；任何失败都静默降级，绝不影响审查主流程）
======================================================================
  1. `~/.workbuddy/workbuddy.db` 的 `sessions` 表
     —— 列含 `id / title / model / status / updated_at / deleted_at / cwd`。
     取「最近活动且未删除」的会话：工具调用发生在该会话的某一轮里，
     那个会话必然就是更新时间最新的一个。
  2. `~/.workbuddy/models.json`
     —— WorkBuddy 的自定义模型清单（每项含 `id / url / apiKey`）。
     本地 LM Studio 与用户自行登记的云端接入都在这里，因此它就是
     「模型名 → 可直达端点」的映射表。

======================================================================
模型名约定（实测取值）
======================================================================
    "custom-local:google/gemma-4-e4b"   → 本地 LM Studio（前缀 custom-local:）
    "custom-local:qwen2.5-14b-instruct" → 本地 LM Studio
    "deepseek-v4.1-flash" / "hy3" / "kimi-k3-1"
                                        → WorkBuddy 云端模型。
      工具进程**没有**这些云模型的凭据（凭据在 WorkBuddy 客户端内部），
      因此默认不可直达 —— 除非用户在 models.json 里登记了同名接入
      （例如 {"id": "deepseek-v4.1-flash", "url": "https://api.deepseek.com/v1",
             "apiKey": "sk-..."}），此时本模块会解析出该端点并直接使用。

======================================================================
兼容旧行为
======================================================================
`config.MODEL_POLICY` 控制策略：
    "session"（默认）→ 跟随会话模型，不可直达时回退本机 LM Studio 并记录原因
    "local"          → 旧行为：只看本机 LM Studio 的已加载/可用模型
    "pinned"         → 始终使用 AGENT_MODEL / 显式指定模型
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from config import config

logger = logging.getLogger(__name__)

LOCAL_PREFIX = "custom-local:"
_WORKBUDDY_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy")

#: 读 DB / models.json 的缓存（避免一次审查里反复读盘）
_CACHE_TTL_SEC = 3.0
_cache: dict = {"at": 0.0, "session": None, "models_at": 0.0, "models": None}


@dataclass
class Backend:
    """一个可调用后端：端点 + 密钥 + 模型名。"""

    model: str                      # 实际发给后端的模型 id
    base_url: str = ""
    api_key: str = ""
    reachable: bool = True          # 本工具能否直达
    source: str = ""                # 人类可读的来源说明
    session_model: str = ""         # 会话里记录的原始模型名（可能带 custom-local: 前缀）
    reason: str = ""                # 不可直达时的原因

    def describe(self) -> str:
        if self.reachable:
            return f"{self.model} ← {self.source}"
        return f"{self.session_model}（本机不可直达：{self.reason}）"


def _workbuddy_db_path() -> str:
    return os.getenv("WORKBUDDY_DB", os.path.join(_WORKBUDDY_DIR, "workbuddy.db"))


def _models_json_path() -> str:
    return os.getenv("WORKBUDDY_MODELS_JSON", os.path.join(_WORKBUDDY_DIR, "models.json"))


# ==================== 1) 读「当前会话使用的模型」 ====================

def read_current_session(force: bool = False) -> Optional[Tuple[str, str]]:
    """返回最近活动且未删除的会话 (session_id, model)；读不到返回 None。"""
    now = time.time()
    if not force and _cache["session"] is not None and now - _cache["at"] < _CACHE_TTL_SEC:
        return _cache["session"]

    db = _workbuddy_db_path()
    result = None
    if os.path.exists(db):
        try:
            # 只读打开，避免干扰 WorkBuddy 正在使用的数据库
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3.0)
            try:
                cur = con.cursor()
                cur.execute(
                    "select id, model from sessions "
                    "where deleted_at is null and model is not null and model != '' "
                    "order by updated_at desc limit 5"
                )
                for sid, model in cur.fetchall():
                    if model:
                        result = (str(sid), str(model))
                        break
            finally:
                con.close()
        except Exception as e:
            logger.debug("读取 WorkBuddy 会话库失败（忽略，回退本地模型）: %s", e)

    _cache["session"] = result
    _cache["at"] = now
    return result


# ==================== 2) 读 models.json（模型名 → 端点映射） ====================

def load_registered_models(force: bool = False) -> List[dict]:
    """读 ~/.workbuddy/models.json（WorkBuddy 自定义模型清单）。"""
    path = _models_json_path()
    try:
        mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
    except Exception:
        mtime = 0.0
    if not force and _cache["models"] is not None and mtime == _cache["models_at"]:
        return _cache["models"]
    entries: List[dict] = []
    try:
        if mtime:
            data = json.loads(open(path, encoding="utf-8", errors="replace").read())
            if isinstance(data, list):
                entries = [e for e in data if isinstance(e, dict)]
    except Exception as e:
        logger.debug("读取 WorkBuddy models.json 失败（忽略）: %s", e)
    _cache["models"] = entries
    _cache["models_at"] = mtime
    return entries


def match_registered(model_key: str) -> Optional[dict]:
    """在 models.json 中按 id 查找接入配置（容忍 vendor 前缀差异）。"""
    key = (model_key or "").strip().lower()
    if not key:
        return None
    tail = key.split("/")[-1]
    for e in load_registered_models():
        eid = str(e.get("id") or "").strip()
        if not eid:
            continue
        eid_low = eid.lower()
        if eid_low == key or eid_low.split("/")[-1] == tail:
            return e
    return None


# ==================== 3) 映射与解析 ====================

def map_session_model(session_model: str) -> Optional[Backend]:
    """把「会话里记录的模型名」映射为可直达后端。"""
    raw = (session_model or "").strip()
    if not raw:
        return None

    # 3.1 本地模型：custom-local:<lmstudio-model-id>
    if raw.startswith(LOCAL_PREFIX):
        mid = raw[len(LOCAL_PREFIX):].strip()
        return Backend(
            model=mid,
            base_url=config.LM_STUDIO_BASE_URL,
            api_key=config.LM_STUDIO_API_KEY,
            reachable=True,
            source="本机 LM Studio（跟随会话模型）",
            session_model=raw,
        )

    # 3.2 用户已在 models.json 里登记过同名接入 → 直接用它（含云端）
    entry = match_registered(raw)
    url = str((entry or {}).get("url") or "").strip()
    if entry and url.startswith(("http://", "https://")):
        return Backend(
            model=str(entry.get("id") or raw),
            base_url=url,
            api_key=str(entry.get("apiKey") or "x"),
            reachable=True,
            source=f"models.json 已登记的接入（{url}）",
            session_model=raw,
        )

    # 3.3 WorkBuddy 云端模型且未登记 → 工具没有凭据，不可直达
    return Backend(
        model=raw,
        base_url="",
        api_key="",
        reachable=False,
        session_model=raw,
        reason="这是 WorkBuddy 的云端模型，凭据在客户端内部，本工具无法直接调用；"
               "如需让审查也用云端，请在 ~/.workbuddy/models.json 登记同名接入（id/url/apiKey）",
    )


def resolve_explicit(name: str, source: str = "显式指定") -> Backend:
    """显式模型名（AGENT_MODEL / 工具入参）：优先 models.json 登记，否则视为本机 LM Studio 模型。"""
    entry = match_registered(name)
    url = str((entry or {}).get("url") or "").strip()
    if entry and url.startswith(("http://", "https://")):
        return Backend(model=str(entry.get("id") or name), base_url=url,
                       api_key=str(entry.get("apiKey") or "x"), reachable=True,
                       source=f"{source} → models.json 已登记接入（{url}）", session_model=name)
    return Backend(model=name, base_url=config.LM_STUDIO_BASE_URL,
                   api_key=config.LM_STUDIO_API_KEY, reachable=True,
                   source=f"{source} → 本机 LM Studio", session_model=name)


def resolve(preferred_model: Optional[str] = None) -> Optional[Backend]:
    """统一入口：显式指定 > 会话模型 > None（表示交给引擎按本地默认处理）。"""
    if preferred_model:
        return resolve_explicit(preferred_model, "工具入参指定")
    if config.AGENT_MODEL:
        return resolve_explicit(config.AGENT_MODEL, "AGENT_MODEL 环境变量")
    cur = read_current_session()
    if cur:
        return map_session_model(cur[1])
    return None


def describe_resolution(preferred_model: Optional[str] = None) -> dict:
    """诊断用：返回解析结果的可序列化摘要（ping 工具使用）。"""
    policy = getattr(config, "MODEL_POLICY", "session")
    info = {
        "policy": policy,
        "session": None,
        "session_model": None,
        "resolved": None,
        "reachable": None,
    }
    cur = read_current_session(force=True)
    if cur:
        info["session"] = cur[0]
        info["session_model"] = cur[1]
    if policy == "session":
        b = resolve(preferred_model)
        if b is not None:
            info["resolved"] = b.model
            info["reachable"] = b.reachable
            info["detail"] = b.describe()
    return info
