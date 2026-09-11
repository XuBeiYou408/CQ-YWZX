"""
多模型统一适配器模块 - 本地 LM Studio 与云端大模型热切换
"""
import time
from typing import Any, Dict, TypedDict
import httpx


class ModelStatus(TypedDict):
    active_provider: str  # "local" | "cloud"
    local_status: str  # "available" | "unavailable" | "checking"
    local_provider: str  # "lm_studio" | "ollama" | ""
    local_model: str
    local_latency_ms: int
    cloud_status: str  # "configured" | "unconfigured" | "error"
    cloud_provider: str
    cloud_model: str
    cloud_base_url: str
    cloud_api_key_set: bool


async def probe_local_models() -> Dict[str, Any]:
    """
    快速探测本地模型服务（LM Studio 1234，Ollama 11434）
    """
    async with httpx.AsyncClient(timeout=2.5) as client:
        # 1. 优先探测 LM Studio
        try:
            start_t = time.perf_counter()
            resp = await client.get("http://127.0.0.1:1234/v1/models")
            latency = int((time.perf_counter() - start_t) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                model_name = models[0].get("id", "qwen3.8-27b") if models else "qwen3.8-27b"
                return {
                    "available": True,
                    "provider": "lm_studio",
                    "model_name": model_name,
                    "latency_ms": latency,
                }
        except Exception:
            pass

        # 2. 备选探测 Ollama
        try:
            start_t = time.perf_counter()
            resp = await client.get("http://127.0.0.1:11434/v1/models")
            latency = int((time.perf_counter() - start_t) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                model_name = models[0].get("id", "qwen") if models else "default"
                return {
                    "available": True,
                    "provider": "ollama",
                    "model_name": model_name,
                    "latency_ms": latency,
                }
        except Exception:
            pass

    return {
        "available": False,
        "provider": "",
        "model_name": "",
        "latency_ms": -1,
    }


async def get_model_status(cfg: dict) -> ModelStatus:
    local_probe = await probe_local_models()
    cloud_cfg = cfg.get("cloud_model", {})
    api_key = cloud_cfg.get("api_key", "").strip()

    cloud_status = "configured" if api_key else "unconfigured"

    return {
        "active_provider": cfg.get("active_provider", "local"),
        "local_status": "available" if local_probe["available"] else "unavailable",
        "local_provider": local_probe["provider"],
        "local_model": local_probe["model_name"] or cfg.get("local_model", {}).get("model_name", "qwen3.8-27b"),
        "local_latency_ms": local_probe["latency_ms"],
        "cloud_status": cloud_status,
        "cloud_provider": cloud_cfg.get("provider", "deepseek"),
        "cloud_model": cloud_cfg.get("model_name", "deepseek-chat"),
        "cloud_base_url": cloud_cfg.get("base_url", "https://api.deepseek.com/v1"),
        "cloud_api_key_set": bool(api_key),
    }


async def test_cloud_connection(base_url: str, api_key: str, model_name: str, timeout: int = 12) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }
    try:
        start_t = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            latency = int((time.perf_counter() - start_t) * 1000)
            if resp.status_code == 200:
                return {"success": True, "latency_ms": latency, "error": ""}
            else:
                return {"success": False, "latency_ms": latency, "error": f"HTTP {resp.status_code}: {resp.text[:150]}"}
    except Exception as e:
        return {"success": False, "latency_ms": -1, "error": str(e)}


async def generate_chat(prompt: str, system_prompt: str, cfg: dict, json_mode: bool = False) -> str:
    active = cfg.get("active_provider", "local")
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    if active == "local":
        probe = await probe_local_models()
        if probe["available"] and probe["provider"] == "ollama":
            base_url = cfg.get("local_model", {}).get("ollama_url", "http://127.0.0.1:11434/v1")
        else:
            base_url = cfg.get("local_model", {}).get("lm_studio_url", "http://127.0.0.1:1234/v1")

        model = probe["model_name"] or cfg.get("local_model", {}).get("model_name", "qwen3.8-27b")
        headers = {"Content-Type": "application/json"}
        url = f"{base_url.rstrip('/')}/chat/completions"
        timeout = cfg.get("local_model", {}).get("timeout", 60)
    else:
        cloud_cfg = cfg.get("cloud_model", {})
        base_url = cloud_cfg.get("base_url", "https://api.deepseek.com/v1")
        model = cloud_cfg.get("model_name", "deepseek-chat")
        api_key = cloud_cfg.get("api_key", "")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = f"{base_url.rstrip('/')}/chat/completions"
        timeout = cloud_cfg.get("timeout", 60)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                # 某些本地模型不支持 response_format，自动重试无 response_format
                if json_mode and "response_format" in resp.text:
                    payload.pop("response_format", None)
                    resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"模型调用失败 (HTTP {resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.ConnectError:
            raise RuntimeError(f"无法连接到模型服务: {url}，请确认 LM Studio 或 API 服务已启动")
        except httpx.TimeoutException:
            raise RuntimeError(f"模型推理超时 ({timeout}s)，请缩短周报文本或切换到云端模型")