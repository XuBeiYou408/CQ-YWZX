import asyncio
import re
import time
from typing import Any, Dict, TypedDict

import httpx


class ModelStatus(TypedDict):
    active_provider: str  # "local" | "cloud"
    local_status: str     # "available" | "unavailable" | "checking"
    local_provider: str   # "lm_studio" | "ollama" | ""
    local_model: str      # ???? "qwen3.8-27b" ? ""
    local_latency_ms: int  # -1 ????
    cloud_status: str     # "configured" | "unconfigured" | "error"
    cloud_provider: str
    cloud_model: str


async def _probe_single(provider: str, base_url: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/models")
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                model_name = ""
                if isinstance(models, list) and models:
                    model_ids = [m.get("id", "") for m in models if isinstance(m, dict)]
                    if "qwen3.8-27b" in model_ids:
                        model_name = "qwen3.8-27b"
                    elif model_ids:
                        model_name = model_ids[0]
                return {
                    "provider": provider,
                    "model_name": model_name,
                    "latency_ms": latency_ms,
                    "available": True,
                }
    except Exception:
        pass

    return {
        "provider": provider,
        "model_name": "",
        "latency_ms": -1,
        "available": False,
    }


async def probe_local_models(
    lm_url: str = "http://127.0.0.1:1234/v1",
    ollama_url: str = "http://127.0.0.1:11434/v1",
) -> Dict[str, Any]:
    """
    ? httpx?timeout=3s????? LM Studio (1234) ? Ollama (11434) ? /v1/models ??
    ?????{"provider": "lm_studio"|"ollama"|"", "model_name": str, "latency_ms": int, "available": bool}
    ???? LM Studio????1234???LM Studio??????Ollama
    ?????????????
    ???????????????
    """
    lm_res, ollama_res = await asyncio.gather(
        _probe_single("lm_studio", lm_url),
        _probe_single("ollama", ollama_url),
        return_exceptions=False,
    )

    if isinstance(lm_res, dict) and lm_res.get("available"):
        return lm_res

    if isinstance(ollama_res, dict) and ollama_res.get("available"):
        return ollama_res

    return {
        "provider": "",
        "model_name": "",
        "latency_ms": -1,
        "available": False,
    }


async def get_model_status(cfg: Dict[str, Any]) -> ModelStatus:
    """
    ?? probe_local_models() ??????
    ?? cfg ??????????????api_key???
    ???? ModelStatus
    """
    local_cfg = cfg.get("local_model", {})
    lm_url = local_cfg.get("lm_studio_url", "http://127.0.0.1:1234/v1")
    ollama_url = local_cfg.get("ollama_url", "http://127.0.0.1:11434/v1")

    local_info = await probe_local_models(lm_url=lm_url, ollama_url=ollama_url)

    cloud_cfg = cfg.get("cloud_model", {})
    cloud_provider = cloud_cfg.get("provider", "")
    cloud_model = cloud_cfg.get("model_name", "")
    cloud_key = str(cloud_cfg.get("api_key", "")).strip()

    local_available = bool(local_info.get("available", False))
    local_model = local_info.get("model_name", "") or local_cfg.get("model_name", "")

    return {
        "active_provider": cfg.get("active_provider", "local"),
        "local_status": "available" if local_available else "unavailable",
        "local_provider": local_info.get("provider", "") if local_available else "",
        "local_model": local_model if local_available else "",
        "local_latency_ms": local_info.get("latency_ms", -1) if local_available else -1,
        "cloud_status": "configured" if bool(cloud_key) else "unconfigured",
        "cloud_provider": cloud_provider,
        "cloud_model": cloud_model,
    }


async def test_cloud_connection(
    base_url: str, api_key: str, model_name: str, timeout: int = 10
) -> Dict[str, Any]:
    """
    ?????? chat completion ???prompt="ping", max_tokens=1?? {base_url}/chat/completions
    ?? {"success": bool, "latency_ms": int, "error": str}
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    url = f"{base_url.rstrip('/')}/chat/completions"
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                return {"success": True, "latency_ms": latency_ms, "error": ""}
            else:
                return {
                    "success": False,
                    "latency_ms": latency_ms,
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                }
    except Exception as e:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {"success": False, "latency_ms": latency_ms, "error": str(e)}


async def _resolve_local_model(base_url: str, configured: str) -> str:
    """确认本地推理服务是否真的提供配置的模型名。

    LM Studio / Ollama 在模型名不存在时会直接返回 400 错误（例如配置写着
    `qwen3.8-27b`，而本地实际只加载了 `qwen3.6-27b`），这会让整条 AI 评估链路
    静默降级为兜底结果。此处做一次轻量探测：配置名不存在时回退到本地第一个
    可用的对话模型（排除 embedding 模型），保证本地模式始终可评估。
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/models")
            if resp.status_code != 200:
                return configured
            ids = [
                m.get("id", "")
                for m in resp.json().get("data", [])
                if isinstance(m, dict) and m.get("id")
            ]
    except Exception:
        return configured

    if not ids or configured in ids:
        return configured

    # 优先回退到「同族」模型（如配置 qwen3.8-27b -> 回退 qwen 系列），其次第一个非 embedding 模型
    chat_models = [str(m) for m in ids if "embed" not in str(m).lower()]
    stem = "".join(ch for ch in configured if ch.isalpha()).lower()[:4]
    for mid in chat_models:
        if stem and stem in mid.lower():
            print(f"[RecruitAI LLM] 本地服务未提供模型 '{configured}'，已自动回退为同族模型 '{mid}'")
            return mid
    if chat_models:
        print(f"[RecruitAI LLM] 本地服务未提供模型 '{configured}'，已自动回退为 '{chat_models[0]}'")
        return chat_models[0]
    return configured


async def generate_chat(
    prompt: str, system_prompt: str, cfg: Dict[str, Any], json_mode: bool = True
) -> str:
    """
    ?? cfg["active_provider"] ???????????
    ???? lm_studio_url ? ollama_url????????? chat completion
    ???? cloud_model.base_url ??? Authorization: Bearer {api_key}
    ? json_mode=True??? messages ????????"???? JSON?????????"
    ?? httpx.AsyncClient?timeout ? cfg ??
    ???????choices[0].message.content?
    ????????? RuntimeError
    """
    active_provider = cfg.get("active_provider", "local")

    if active_provider == "local":
        local_cfg = cfg.get("local_model", {})
        lm_url = local_cfg.get("lm_studio_url", "http://127.0.0.1:1234/v1")
        ollama_url = local_cfg.get("ollama_url", "http://127.0.0.1:11434/v1")

        probe = await probe_local_models(lm_url=lm_url, ollama_url=ollama_url)
        # 智能双模守护：若本地端侧未启动（如云服务器临时部署环境）且已配置云端 API Key，
        # 自动无缝路由至云端大模型，彻底杜绝因本地未开启而退回到静态硬编码兜底！
        cloud_cfg = cfg.get("cloud_model", {})
        has_cloud_key = bool(str(cloud_cfg.get("api_key", "")).strip())

        if not probe.get("available") and has_cloud_key:
            print(f"[RecruitAI LLM] 本地推理服务离线，检测到云端模型配置已就绪，自动平滑路由至云端: {cloud_cfg.get('model_name')}")
            active_provider = "cloud"
        else:
            if probe.get("provider") == "ollama":
                base_url = ollama_url
            else:
                base_url = lm_url

            model = local_cfg.get("model_name", "qwen3.8-27b")
            model = await _resolve_local_model(base_url, model)
            timeout = float(local_cfg.get("timeout", 45))
            headers = {"Content-Type": "application/json"}

    if active_provider != "local":
        cloud_cfg = cfg.get("cloud_model", {})
        base_url = cloud_cfg.get("base_url", "https://api.deepseek.com/v1")
        api_key = cloud_cfg.get("api_key", "")
        model = cloud_cfg.get("model_name", "deepseek-chat")
        timeout = max(float(cloud_cfg.get("timeout", 60)), 90.0)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    user_content = prompt
    if json_mode:
        user_content = f"{prompt}\n\n请严格只输出合法 JSON 格式，不要输出任何解释、前后缀或 Markdown 代码块标记。"
    messages.append({"role": "user", "content": user_content})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800,
    }

    url = f"{base_url.rstrip('/')}/chat/completions"
    req_timeout = httpx.Timeout(120.0, connect=20.0, read=120.0, write=30.0)

    try:
        async with httpx.AsyncClient(timeout=req_timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"LLM API request failed with status {resp.status_code}: {resp.text}"
                )
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError(f"LLM returned no choices: {data}")
            msg = choices[0].get("message", {})
            content = msg.get("content", "") or ""
            reasoning = msg.get("reasoning_content", "") or ""
            if not content.strip() and reasoning.strip():
                content = reasoning.strip()
            if content:
                content = re.sub(r"<think>[\s\S]*?</think>", "", content, flags=re.IGNORECASE).strip()
                content = re.sub(r"</?think>", "", content).strip()
            return content if content is not None else ""
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"LLM chat generation failed: {e}") from e
