# -*- coding: utf-8 -*-
"""
智审 (Doc-Agent) · 模型管理 API 路由
======================================================================
提供「选择云端模型 / 本地模型」的配置读写与连通性测试：
  GET  /api/model/config       当前配置（密钥脱敏）+ 当前生效模型 + 云端预设列表
  GET  /api/model/local/list   本机 LM Studio 可用模型（区分已加载 / 全部）
  POST /api/model/config       保存配置（选择本地或云端后立即生效，无需重启）
  POST /api/model/test         连通性测试（不传参数则测当前生效配置）

安全：密钥只存本地 `model_config.json`（已 gitignore），接口仅返回掩码与 has_key。
"""
import logging
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter

from app.schemas import APIResponse, ModelConfigRequest, ModelTestRequest
from contract import model_config

logger = logging.getLogger(__name__)
router = APIRouter()


def _section_payload(section) -> Optional[Dict[str, Any]]:
    """把 pydantic 段落转成只含显式提供字段的 dict（None 字段丢弃）"""
    if section is None:
        return None
    data = section.model_dump(exclude_none=True)
    return data or None


@router.get("/config", response_model=APIResponse)
async def get_model_config():
    """读取模型管理配置（API Key 仅返回掩码）"""
    try:
        return APIResponse(data=model_config.masked_view())
    except Exception as e:
        logger.error(f"读取模型配置失败: {e}", exc_info=True)
        return APIResponse(code=500, message=f"读取模型配置失败: {e}")


@router.post("/config", response_model=APIResponse)
async def update_model_config(req: ModelConfigRequest):
    """
    保存模型配置：选择 `local`（本机 LM Studio）或 `cloud`（云端 API）。
    保存后即刻生效（引擎每次审查都会读取当前生效配置），无需重启服务。
    """
    try:
        saved = model_config.save({
            "provider": req.provider,
            "local": _section_payload(req.local),
            "cloud": _section_payload(req.cloud),
        })
        eff = model_config.get_effective()
        msg = (
            f"已切换为本地模型：{eff['model']}（{eff['base_url']}）"
            if eff["is_local"] else
            f"已切换为云端模型：{eff['model']}（{eff['base_url']}）"
        )
        logger.info(f"[模型管理] {msg}")
        return APIResponse(message=msg, data=model_config.masked_view())
    except Exception as e:
        logger.error(f"保存模型配置失败: {e}", exc_info=True)
        return APIResponse(code=500, message=f"保存模型配置失败: {e}")


@router.get("/local/list", response_model=APIResponse)
async def list_local_models(base_url: str = None):
    """列出本机 LM Studio 的模型：已加载（可直接用，无需等待加载）与全部已下载模型"""
    base = (base_url or model_config.load()["local"].get("base_url")
            or model_config.get_effective()["base_url"]).rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base

    loaded, all_models, error = [], [], None

    # 1) LM Studio 专有接口：已加载模型（/api/v0/models）
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{root}/api/v0/models")
            if r.status_code == 200:
                for m in (r.json().get("data") or []):
                    mid = m.get("id")
                    if mid and m.get("state") == "loaded":
                        loaded.append(mid)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    # 2) OpenAI 兼容接口：全部可用模型（/v1/models）
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{base}/models")
            if r.status_code == 200:
                all_models = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
                error = None
            elif error is None:
                error = f"HTTP {r.status_code}"
    except Exception as e:
        if error is None:
            error = f"{type(e).__name__}: {e}"

    # 已加载的排前面
    ordered = loaded + [m for m in all_models if m not in loaded]
    return APIResponse(
        data={
            "base_url": base,
            "connected": bool(all_models or loaded),
            "loaded": loaded,
            "models": ordered,
            "error": None if (all_models or loaded) else error,
        }
    )


@router.post("/test", response_model=APIResponse)
async def test_model_connection(req: ModelTestRequest):
    """
    连通性测试：先用 GET /models 探测端点，失败则退回 1-token 最小对话调用。
    不传参数时测「当前已保存的生效配置」。
    """
    eff = model_config.get_effective()
    cfg = model_config.load()
    provider = (req.provider or eff["provider"]).lower()

    if provider == "cloud":
        preset = req.preset or cfg["cloud"].get("preset") or "deepseek"
        preset_models = model_config.CLOUD_PRESETS.get(preset, {}).get("models") or ["deepseek-chat"]
        base_url = (req.base_url
                    or (cfg["cloud"].get("base_url") if eff["provider"] == "cloud" else "")
                    or model_config.CLOUD_PRESETS.get(preset, {}).get("base_url", ""))
        model = (req.model or "").strip() or (cfg["cloud"].get("model") if eff["provider"] == "cloud" else "") or preset_models[0]
        api_key = (req.api_key or "").strip() or model_config.resolve_cloud_key(cfg["cloud"])
    else:
        base_url = req.base_url or cfg["local"].get("base_url") or eff["base_url"]
        model = (req.model or "").strip() or cfg["local"].get("model") or eff["model"]
        api_key = (req.api_key or "").strip() or cfg["local"].get("api_key") or "lm-studio"

    base_url = (base_url or "").rstrip("/")
    result: Dict[str, Any] = {"provider": provider, "base_url": base_url, "model": model}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    t0 = time.time()

    # 1) 模型列表探测
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(f"{base_url}/models", headers=headers)
        result["latency_ms"] = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            ids = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
            result.update({
                "ok": True,
                "method": "GET /models",
                "models_count": len(ids),
                "model_available": (model in ids) if model else None,
                "models_sample": ids[:8],
                "message": f"连接成功：共 {len(ids)} 个可用模型"
                           + ("" if (not model or model in ids) else f"；注意：{model} 不在列表中"),
            })
            return APIResponse(data=result)
        result["models_endpoint_status"] = r.status_code
    except Exception as e:
        result["models_endpoint_error"] = f"{type(e).__name__}: {e}"

    # 2) 退回最小对话调用
    if not api_key:
        result.update({"ok": False, "message": "缺少 API Key，无法发起对话调用（本地 LM Studio 可随意填 lm-studio）"})
        return APIResponse(data=result)
    try:
        payload = {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        result["latency_ms"] = int((time.time() - t0) * 1000)
        if r.status_code == 200:
            result.update({"ok": True, "method": "POST /chat/completions", "message": "连接成功（最小对话调用通过）"})
        else:
            detail = r.text[:200]
            result.update({"ok": False, "method": "POST /chat/completions",
                           "message": f"调用失败：HTTP {r.status_code} {detail}"})
    except Exception as e:
        result.update({"ok": False, "message": f"调用异常：{type(e).__name__}: {e}"})
    return APIResponse(data=result)
