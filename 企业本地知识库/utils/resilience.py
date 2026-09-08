import asyncio
import logging
from functools import wraps
from typing import Callable, Any

logger = logging.getLogger(__name__)

# 哨兵对象：区分"用户显式传入 fallback=None"与"未传 fallback"
_SENTINEL = object()

# 可重试的瞬态异常类型（网络抖动、超时、限流等）
TRANSIENT_EXCEPTIONS = (
    asyncio.TimeoutError,
    ConnectionError,
    TimeoutError,
    OSError,
)

def _resolve_fallback(fallback: Any, sentinel: Any, last_err: Exception) -> Any:
    """项目 5 修复：安全解析降级兜底方案，防止可调用对象内部二次抛出异常打断降级链路"""
    if fallback is sentinel:
        raise last_err
    if isinstance(fallback, (str, int, float, bool, dict, list, type(None))):
        return fallback
    if callable(fallback):
        try:
            return fallback()
        except Exception as fe:
            logger.error(f"[Retry] fallback 降级函数执行失败: {fe}", exc_info=True)
            raise last_err
    return fallback

def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    timeout: float = 30.0,
    fallback: Any = _SENTINEL
) -> Callable:
    """
    渐进式重试装饰器：
    Layer 1: asyncio.timeout 超时控制
    Layer 2: 指数退避重试（仅对瞬态异常重试，确定性错误直接抛出）
    Layer 3: 安全返回 fallback 降级兜底值
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_err = None
            for attempt in range(max_retries):
                try:
                    if hasattr(asyncio, "timeout"):
                        async with asyncio.timeout(timeout):
                            return await func(*args, **kwargs)
                    else:
                        return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                except TRANSIENT_EXCEPTIONS as e:
                    last_err = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"[Retry] {func.__name__} 第 {attempt+1} 次尝试异常: {e}，将在 {delay}s 后重试...")
                        await asyncio.sleep(delay)
                except Exception as e:
                    logger.error(f"[Retry] {func.__name__} 遇到非瞬态异常: {e}")
                    return _resolve_fallback(fallback, _SENTINEL, e)
            
            logger.error(f"[Retry] {func.__name__} 经过 {max_retries} 次尝试全部失败: {last_err}")
            return _resolve_fallback(fallback, _SENTINEL, last_err or RuntimeError("重试失败未知错误"))
        return wrapper
    return decorator
