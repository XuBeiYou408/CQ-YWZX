# -*- coding: utf-8 -*-
"""
企业本地知识库 —— RAG 检索工作进程（子进程）

======================================================================
为什么需要这个文件（2026-09-11 第三次重构：子进程隔离）
======================================================================
MCP 客户端（WorkBuddy 等）在【会话创建的一瞬间】就把可用工具清单拍成快照。
若本服务此刻尚未完成 initialize 握手，它的工具就不在快照里，用户的首个提问
必然漏调（只能降级为本地文件搜索）。因此本服务的启动关键路径必须满足：
        「进程启动 → 协议握手完成」< 1 秒

但检索所需的重型 C 扩展（torch / faiss / sklearn / sentence_transformers …）
在 Windows 上只能在【当前进程的主线程】完成首次 import —— 放到后台线程会撞上
OS Loader Lock，与 anyio 事件循环互等死锁（已在本机实测复现，非猜测）。
这部分约 6~7 秒，无法后台化，也就无法从握手路径上消除。

解法：换一个进程去装它们。
    父进程 mcp_server.py 只加载 MCP 协议框架即启动 stdio 服务，握手亚秒级完成，
    工具立刻进入客户端工具清单快照。
    本文件作为【独立子进程】运行：它有自己的主线程、不共享父进程的事件循环，
    因此可以自由加载全部重量级依赖并预热检索链路。父进程通过 stdin/stdout 上的
    JSON 行协议与本进程通信（不占用 MCP 自己的 stdio 通道，互不干扰）。

代价（已与用户确认接受）：每次新会话多一个子进程，首次检索若子进程尚未预热完
则需等待其就绪；检索内核与算法一行未改。
======================================================================
通信协议（每行一个 JSON 对象，UTF-8，行分隔）
======================================================================
    父 → 子：
        {"cmd": "search", "query": str, "top_k": int}
        {"cmd": "clear_cache"}          # 知识库增删文档后清理检索器缓存
        {"cmd": "ping"}
        {"cmd": "shutdown"}
    子 → 父：
        {"type": "ready", "boot_ms": int}       # 预热完成，仅发一次
        {"type": "boot_error", "error": str}    # 预热失败，仅发一次
        {"ok": true,  "docs": [{"source": str, "content": str}], "elapsed_ms": int}
        {"ok": false, "error": str}
"""

import json
import os
import sys
import time
import traceback

# ---------- 路径与环境自举（须先于任何 rag/config 导入） ----------
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
os.chdir(_BASE_DIR)

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
# 显式禁用 GPU：既避免无显卡机器的 CUDA 探测开销，也让 config.py 跳过 1.4 秒的
# 子进程自检。CPU 跑 BGE-base 足以满足本地制度文档检索。
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# 协议通道独占真实 stdout；随后把 sys.stdout 改道 stderr，
# 使子进程内任何 stray print / 第三方库输出都不会污染 JSON 协议流。
_PROTO_OUT = sys.stdout
_PROTO_IN = sys.stdin
sys.stdout = sys.stderr


def _send(obj) -> None:
    """向父进程发送一条协议消息（单行 JSON）。"""
    try:
        _PROTO_OUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
        _PROTO_OUT.flush()
    except Exception:
        # 父进程已消失/管道断裂：交由主循环的 EOF 逻辑退出
        pass


def _trace(msg: str) -> None:
    """启动诊断日志 → stderr（即父进程 stderr，最终落到 MCP 服务日志）。"""
    print(f"[rag-worker {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# ==================== 预热与就绪状态 ====================
_STATE = {"ready": False, "error": None}


def _warmup() -> bool:
    """在子进程主线程完成重型依赖加载与检索链路预热。

    只在子进程的主线程执行——这里没有 anyio 事件循环，DLL 加载不会触发
    OS Loader Lock 死锁，所以可以放心把 6~7 秒的导入放在这条路径上。
    """
    if _STATE["ready"]:
        return True
    _STATE["error"] = None
    try:
        _trace("加载重型依赖（torch/faiss/pymupdf/scipy/sklearn/sentence_transformers）...")
        import torch                    # noqa: F401
        import faiss                    # noqa: F401
        import pymupdf                  # noqa: F401
        import scipy                    # noqa: F401
        import sklearn                  # noqa: F401
        import sentence_transformers    # noqa: F401

        _trace("构建向量检索器与 BM25 索引 ...")
        from rag.retriever import get_retrievers
        get_retrievers()

        _trace("加载 BGE 向量模型 ...")
        from rag.embeddings import embeddings
        embeddings.embed_query("预热")   # 将 BGE 模型整体载入内存

        _STATE["ready"] = True
        _trace("预热完成，检索链路就绪。")
        return True
    except Exception as e:
        _STATE["error"] = f"{type(e).__name__}: {e}"
        _trace(f"预热失败：{_STATE['error']}")
        traceback.print_exc(file=sys.stderr)
        return False


# ==================== 命令处理 ====================
# 检索链路内部使用 asyncio（并发召回 + to_thread 重排），复用一个常驻事件循环，
# 避免每次请求都新建/销毁事件循环。
import asyncio  # noqa: E402

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _do_search(query: str, top_k: int):
    """执行检索并返回可 JSON 序列化的精简文档列表。"""
    from rag.retriever import zhaohui_and_rerank

    docs = _LOOP.run_until_complete(
        zhaohui_and_rerank(query, return_documents=True)
    )
    docs = docs[: max(1, int(top_k))]

    payload = []
    for doc in docs:
        meta = getattr(doc, "metadata", None) or {}
        content = meta.get("dad_content") or getattr(doc, "page_content", "")
        payload.append({
            "source": str(meta.get("source", "")),
            "content": str(content),
        })
    return payload


def _do_clear_cache() -> None:
    """文档增删后清理检索器缓存，使下次检索重建索引（仅就绪时才有意义）。"""
    if not _STATE["ready"]:
        return
    from rag import retriever as _ret_mod
    with _ret_mod._retriever_lock:
        _ret_mod._retriever_cache.clear()


def _handle(req: dict) -> bool:
    """处理一条请求。返回 False 表示应当退出进程。"""
    cmd = req.get("cmd")

    if cmd == "shutdown":
        return False

    if cmd == "ping":
        _send({"ok": True, "ready": _STATE["ready"], "error": _STATE["error"]})
        return True

    if cmd == "clear_cache":
        try:
            _do_clear_cache()
            _send({"ok": True, "ready": _STATE["ready"]})
        except Exception as e:
            _send({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return True

    if cmd == "search":
        started = time.time()
        # 预热未完成时在此等待（父进程已缓存 boot_error 时会立即返回错误）
        if not _STATE["ready"] and not _warmup():
            _send({"ok": False, "error": _STATE["error"] or "未知原因"})
            return True
        try:
            docs = _do_search(req.get("query") or "企业制度", req.get("top_k") or 2)
            _send({
                "ok": True,
                "docs": docs,
                "elapsed_ms": int((time.time() - started) * 1000),
            })
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            _send({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return True

    _send({"ok": False, "error": f"未知命令：{cmd}"})
    return True


def main() -> int:
    boot_started = time.time()

    # 1) 先完成自身预热，再告知父进程
    if _warmup():
        _send({"type": "ready", "boot_ms": int((time.time() - boot_started) * 1000)})
    else:
        _send({"type": "boot_error", "error": _STATE["error"]})

    # 2) 逐行读取请求；父进程退出 → stdin EOF → 本进程自然结束（孤儿进程自清理）
    try:
        for raw in _PROTO_IN:
            raw = raw.strip()
            if not raw:
                continue
            try:
                req = json.loads(raw)
            except Exception:
                continue  # 忽略无法解析的行，保持协议健壮
            if not isinstance(req, dict):
                continue
            if not _handle(req):
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            _LOOP.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
