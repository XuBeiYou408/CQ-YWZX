import os
import time
import logging
import threading
from typing import List, Optional, Any, Dict
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_community.chat_message_histories import SQLChatMessageHistory, RedisChatMessageHistory
from config import REDIS_TTL, LOCAL_DB_PATH, COMPACTION_THRESHOLD, CONTEXT_MAX_TOKENS, REDIS_URL

logger = logging.getLogger(__name__)

sqlite_absolute_path = os.path.abspath(os.path.join(LOCAL_DB_PATH, "agent_memory.db"))
SQLITE_DB_URL = f"sqlite:///{sqlite_absolute_path.replace(os.sep, '/')}"

# ==================== 优化点 (T5): Redis 单例连接池与健康探活缓存 ====================
_redis_pool = None
_redis_healthy: Optional[bool] = None
_redis_check_time: float = 0.0
HEALTH_CHECK_INTERVAL: float = 30.0
_redis_lock = threading.Lock()

# H3 & R2-L5 修复：全内存降级存储字典及并发锁
_in_memory_fallback: Dict[str, Any] = {}
_in_memory_lock = threading.Lock()

def _get_redis_pool():
    global _redis_pool, _redis_healthy, _redis_check_time
    if not REDIS_URL:
        return None
        
    now = time.monotonic()
    if _redis_healthy is not None and (now - _redis_check_time) < HEALTH_CHECK_INTERVAL:
        return _redis_pool if _redis_healthy else None
        
    with _redis_lock:
        # Double-check
        if _redis_healthy is not None and (now - _redis_check_time) < HEALTH_CHECK_INTERVAL:
            return _redis_pool if _redis_healthy else None
        try:
            if _redis_pool is None:
                import redis
                _redis_pool = redis.ConnectionPool.from_url(REDIS_URL, socket_timeout=3, max_connections=10)
            import redis
            client = redis.Redis(connection_pool=_redis_pool)
            client.ping()
            _redis_healthy = True
        except Exception as e:
            logger.warning(f"Redis 连接与探活失败 ({type(e).__name__}): {e}。将降级为本地 SQLite。")
            _redis_healthy = False
        _redis_check_time = now
        return _redis_pool if _redis_healthy else None

# ==================== 自适应获取会话记忆 ====================
def huode_huibao_jiliu(session_id: str) -> BaseChatMessageHistory:
    pool = _get_redis_pool()
    if pool is not None:
        try:
            return RedisChatMessageHistory(
                session_id=f"agent:session:{session_id}",
                url=REDIS_URL,
                key_prefix="agent:session:",
                ttl=REDIS_TTL
            )
        except Exception as e:
            logger.warning(f"Redis 缓存接入失败: {e}，自动降级为 SQLite")

    try:
        os.makedirs(os.path.dirname(sqlite_absolute_path), exist_ok=True)
        return SQLChatMessageHistory(
            session_id=session_id,
            connection=SQLITE_DB_URL,
            table_name="message_store"
        )
    except Exception as e:
        logger.error(f"SQLite 初始化失败: {e}，自动降级为内存 Memory")
        from langchain_core.chat_history import InMemoryChatMessageHistory
        with _in_memory_lock:
            if session_id not in _in_memory_fallback:
                _in_memory_fallback[session_id] = InMemoryChatMessageHistory()
            return _in_memory_fallback[session_id]

def qingkong_huibao_jiliu(session_id: str) -> bool:
    try:
        history = huode_huibao_jiliu(session_id)
        history.clear()
        with _in_memory_lock:
            if session_id in _in_memory_fallback:
                _in_memory_fallback.pop(session_id, None)
        logger.info(f"已成功清空会话 {session_id} 的全部历史记忆。")
        return True
    except Exception as e:
        logger.error(f"清空会话 {session_id} 记忆失败: {e}")
        return False

# ==================== 优化点 (T4): Claude Code 同款就地微压缩 + 强约束摘要 ====================
COMPACTION_PROMPT = """请将以下多轮对话历史压缩为一段结构化摘要，严格遵守以下约束：

1. 【用户核心意图】：用一句话概括用户贯穿整段对话的根本目标
2. 【已确认的关键结论】：列出对话中已经达成共识或已经回答清楚的核心事实（最多 5 条）
3. 【未解决的遗留问题】：列出对话中尚未解答或仍在讨论中的问题（如果有）

输出格式严格为：
[摘要] 用户意图：...
已确认：1. ... 2. ... 3. ...
遗留：1. ...（若无则写"无"）

---
以下是需要压缩的对话历史：
{history}"""

def estimate_tokens(text: str) -> int:
    """粗估 Token 数：中文 ~1.5 token/字，英文 ~1.3 token/word"""
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en_words = len(text.split()) - cn_chars
    return int(cn_chars * 1.5 + max(en_words, 0) * 1.3)

async def compact_history(messages: List[Any], llm: Any) -> str:
    """
    Claude Code 同款就地微压缩：
    当历史 Token 超过阈值时，将早期对话压缩为结构化摘要，
    只保留最近 2 轮原始对话（4 条消息）+ 摘要前缀。
    无论对话多少轮，上下文始终控制在 Token 预算内，且不丢失任何关键决策信息。
    """
    if not messages:
        return ""

    lines = []
    for msg in messages:
        role = "User" if msg.type == "human" else "AI"
        lines.append(f"{role}: {msg.content}")
    full_history = "\n".join(lines)

    total_tokens = estimate_tokens(full_history)

    if total_tokens <= COMPACTION_THRESHOLD:
        return full_history

    recent_count = min(4, len(messages))
    early_messages = messages[:-recent_count]
    recent_messages = messages[-recent_count:]

    early_text = "\n".join(
        f"{'User' if m.type == 'human' else 'AI'}: {m.content}"
        for m in early_messages
    )

    from langchain_core.messages import HumanMessage
    try:
        summary_response = await llm.ainvoke([
            HumanMessage(content=COMPACTION_PROMPT.format(history=early_text))
        ])
        compacted_summary = summary_response.content
    except Exception as e:
        # C2 & 项目 6 修复：当微压缩失败时，按 Token 预算截断模式安全退避；单条消息过长时硬截断保证记忆保留
        logger.warning(f"微压缩生成失败 ({e})，退避为 Token 预算截断模式")
        budget_lines = []
        budget_tokens = 0
        for msg in reversed(messages):
            role = "User" if msg.type == "human" else "AI"
            line = f"{role}: {msg.content}"
            line_tokens = estimate_tokens(line)
            if budget_tokens + line_tokens > CONTEXT_MAX_TOKENS:
                if not budget_lines:
                    # 单条超预算也强制保留截断版，避免清空上下文
                    budget_lines.append(line[:CONTEXT_MAX_TOKENS])
                break
            budget_lines.insert(0, line)
            budget_tokens += line_tokens
        return "\n".join(budget_lines)

    recent_text = "\n".join(
        f"{'User' if m.type == 'human' else 'AI'}: {m.content}"
        for m in recent_messages
    )

    result = f"{compacted_summary}\n\n--- 以下是最近的对话 ---\n{recent_text}"
    logger.info(
        f"Claude Code 就地微压缩完成: {total_tokens} tokens -> ~{estimate_tokens(result)} tokens "
        f"(已压缩 {len(early_messages)} 条早期历史)"
    )
    return result
