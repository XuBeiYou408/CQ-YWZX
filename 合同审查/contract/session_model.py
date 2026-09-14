# -*- coding: utf-8 -*-
"""读取「当前 WorkBuddy 会话正在使用的本地模型」，作为审查选模型的提示。

======================================================================
只做一件事
======================================================================
告诉引擎：用户此刻在会话里选的是哪个**本地 LM Studio 模型**。
数据源是 `~/.workbuddy/workbuddy.db` 的 `sessions` 表（最近活动且未删除的会话，
其 `model` 列形如 `custom-local:<lmstudio-model-id>`）。

======================================================================
为什么只认本地模型（重要）
======================================================================
审查推理跑在本机 LM Studio：
  · 会话用的是**本地**模型 → 那个模型此刻必然已加载（用户正在和它对话），
    直接复用它最省时，也避免 LM Studio 因换模型而卸载/重载（时延会飙升到分钟级）。
  · 会话用的是**云端**模型（deepseek-v4.1-flash / hy3 / kimi-* 等）→ 工具进程拿不到
    WorkBuddy 的云端凭据，本模块**不做任何干预**，交回引擎原有的
    「优先选已加载模型」逻辑（即上一版架构的行为）。

本模块不做任何网络调用；任何异常都静默返回 None，绝不影响审查主流程。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Optional

logger = logging.getLogger(__name__)

LOCAL_PREFIX = "custom-local:"
_DEFAULT_DB = os.path.join(
    os.getenv("WORKBUDDY_DIR", os.path.join(os.path.expanduser("~"), ".workbuddy")),
    "workbuddy.db",
)

_cache: dict = {"at": 0.0, "value": None, "fetched": False}


def read_session_local_model(ttl: float = 30.0) -> Optional[str]:
    """返回当前会话正在使用的本地 LM Studio 模型 id（已去掉 `custom-local:` 前缀）。

    - 会话用的是云端模型 / 读不到库 / 任何异常 → 返回 None
    - 结果缓存 `ttl` 秒（同一轮审查里只读一次）
    """
    now = time.time()
    if _cache["fetched"] and now - _cache["at"] < ttl:
        return _cache["value"]

    value: Optional[str] = None
    db = os.getenv("WORKBUDDY_DB", _DEFAULT_DB)
    try:
        if os.path.exists(db):
            # 只读打开，不干扰 WorkBuddy 正在使用的数据库
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3.0)
            try:
                row = con.execute(
                    "select model from sessions "
                    "where deleted_at is null and model is not null and model != '' "
                    "order by updated_at desc limit 1"
                ).fetchone()
            finally:
                con.close()
            raw = (row[0] if row else "") or ""
            if raw.startswith(LOCAL_PREFIX):
                value = raw[len(LOCAL_PREFIX):].strip() or None
            elif raw:
                logger.debug("会话模型 %r 非本地模型，交回引擎按已加载模型优选", raw)
    except Exception as e:
        logger.debug("读取会话本地模型失败（忽略）: %s", e)

    _cache.update({"at": now, "value": value, "fetched": True})
    return value


def model_id_matches(a: str, b: str) -> bool:
    """比较两个模型 id 是否等价（容忍 vendor 前缀差异，如 google/gemma-4-e4b 与 gemma-4-e4b）。"""
    if not a or not b:
        return False
    a, b = a.strip().lower(), b.strip().lower()
    return a == b or a.split("/")[-1] == b.split("/")[-1]
