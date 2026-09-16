import os
from langchain_openai import ChatOpenAI
import langchain_openai.chat_models.base as _lc_base

# 动态补丁：使 LangChain ChatOpenAI 在流式模式下完整保留 OpenAI 兼容端点 (LM Studio, DeepSeek-R1, Qwen 等) 传回的 reasoning_content 推理思考链
_orig_convert_delta = _lc_base._convert_delta_to_message_chunk

def _patched_convert_delta(_dict, default_class):
    chunk = _orig_convert_delta(_dict, default_class)
    # 提取推理链/思维链内容
    reasoning = _dict.get("reasoning_content") or _dict.get("reasoning") or _dict.get("thought")
    if reasoning and hasattr(chunk, "additional_kwargs"):
        chunk.additional_kwargs["reasoning_content"] = reasoning
    return chunk

_lc_base._convert_delta_to_message_chunk = _patched_convert_delta


def huode_dongtai_llm(
    provider: str = "cloud",
    model_name: str = "deepseek-chat",
    streaming: bool = False,
    temperature: float = 0,
    max_tokens: int = 2048,
    api_key: str = None,
    base_url: str = None
) -> ChatOpenAI:
    """
    动态 LLM 工厂方法：根据前端传入的 provider ("cloud" / "local") 和 model_name 动态实例化 LangChain LLM
    """
    prov = (provider or "cloud").lower().strip()
    target_model = model_name or ("deepseek-chat" if prov == "cloud" else "qwen3.8-27b")

    if prov == "local":
        # 🏠 本地部署模式 (LM Studio / 本地兼容端点，默认 1234 端口)
        resolved_local_base = base_url or os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:1234/v1")
        return ChatOpenAI(
            model=target_model,
            api_key=api_key or "lm-studio",
            base_url=resolved_local_base,
            temperature=temperature,
            streaming=streaming,
            max_tokens=max_tokens,
            request_timeout=60,
            max_retries=1,
        )
    else:
        # ☁️ 云端 API 模式 (DeepSeek / OpenAI 兼容协议)
        resolved_key = api_key or os.getenv('DEEPSEEK_API_KEY') or "sk-placeholder"
        resolved_base = base_url or os.getenv('DEEPSEEK_API_URL', 'https://api.deepseek.com')
        # 智能适配：若配置为智谱开放平台 (bigmodel.cn) 且模型名为默认 deepseek-chat，自动安全映射为 glm-4-flash
        if "bigmodel.cn" in resolved_base and (not model_name or model_name in ("deepseek-chat", "deepseek-reasoner", "")):
            target_model = "glm-4-flash"
        return ChatOpenAI(
            model=target_model,
            api_key=resolved_key,
            base_url=resolved_base,
            temperature=temperature,
            streaming=streaming,
            max_tokens=max_tokens,
            request_timeout=30,
        )

# 默认全局实例 (保持向后兼容)
rewrite_llm = huode_dongtai_llm(provider="cloud", model_name="deepseek-chat", streaming=False, max_tokens=150)
llm = huode_dongtai_llm(provider="cloud", model_name="deepseek-chat", streaming=True, max_tokens=2048)

