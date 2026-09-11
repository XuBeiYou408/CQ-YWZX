"""
企业本地知识库 MCP Server（子进程隔离架构，2026-09-11 第四次重构）
================================================================
通过 stdio JSON-RPC 2.0 协议将知识库检索能力暴露给 WorkBuddy 等 AI 助手。

支持的 Tools：
  - search_knowledge_base     : 混合检索（向量 + BM25 + 重排精排）
  - list_knowledge_documents  : 列出当前知识库中所有已索引文档
  - add_document_to_knowledge : 向知识库新增并索引文档（支持 pdf/docx/md/txt）

启动架构（为什么必须这样，详见 rag_worker.py 文件头）：
  WorkBuddy 在会话创建瞬间拍工具清单快照，因此「进程启动 → 握手完成」必须
  亚秒级。而检索所需的重量级 C 扩展（torch/faiss/sklearn/...）在 Windows 上
  只能在进程主线程首次 import——放在本进程后台线程会撞 OS Loader Lock，
  与 anyio 事件循环互等（实测 88~120 秒卡顿乃至死锁）。
  解法：本文件（父进程）只加载 MCP 协议框架即启动 stdio 服务；全部重型依赖
  在子进程 rag_worker.py（有自己的主线程）中加载并预热；本文件通过
  stdin/stdout 上的 JSON 行协议与子进程通信（不占用 MCP 的 stdio 通道）。

容错：
  - 子进程预热未完成时，检索调用在后台线程等待其就绪（最长 240 秒），对调用方透明
  - 子进程崩溃/EOF → 下次请求自动重启并重试一次
  - 父进程退出 → 发送 shutdown + stdin EOF，子进程自行退出（无孤儿进程）
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from typing import Union

# ---------- 路径与环境自举 ----------
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
os.chdir(_BASE_DIR)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from dotenv import load_dotenv
load_dotenv(os.path.join(_BASE_DIR, ".env"))

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("kb-mcp")

# ==================================================================
# 检索子进程管理（JSON 行协议，见 rag_worker.py 文件头的协议定义）
# ==================================================================

_BOOT_WAIT_SECONDS = 240     # 等待子进程预热就绪（冷启动含 torch 导入约 7~15 秒）
_CALL_TIMEOUT_SECONDS = 300  # 单次检索响应超时


class _WorkerManager:
    """管理与 rag_worker.py 子进程的连接：spawn / 预热等待 / 请求转发 / 崩溃重启。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue | None = None
        self._ready = False
        self._boot_error: str | None = None

    # ---- 内部：进程与读取线程 ----
    def _spawn(self):
        import queue as _q
        self._proc = subprocess.Popen(
            [sys.executable, os.path.join(_BASE_DIR, "rag_worker.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # 继承父进程 stderr → 落入 MCP 服务日志，便于诊断
        )
        self._queue = _q.Queue()
        self._ready = False
        self._boot_error = None
        threading.Thread(target=self._reader, args=(self._proc, self._queue),
                         daemon=True, name="rag-worker-reader").start()
        log.info("检索子进程已启动 (pid=%s)", self._proc.pid)

    @staticmethod
    def _reader(proc, q):
        try:
            for raw in proc.stdout:
                q.put(raw.decode("utf-8", errors="replace"))
        except Exception:
            pass
        q.put(None)  # EOF 哨兵

    def _send(self, obj):
        self._proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        self._proc.stdin.flush()

    def _recv(self, timeout) -> dict | None:
        """取一条子进程消息；None 表示超时或 EOF。"""
        try:
            raw = self._queue.get(timeout=timeout)
        except Exception:
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw.strip())
        except Exception:
            return None

    def _ensure_ready(self) -> str | None:
        """确保子进程存活且预热完成。返回 None=就绪，否则返回错误说明。"""
        if self._proc is None or self._proc.poll() is not None:
            log.warning("检索子进程不在运行，重新启动...")
            self._spawn()
        if self._ready:
            return None
        if self._boot_error:
            return self._boot_error
        # 读取（已被缓冲的）boot 消息
        msg = self._recv(timeout=_BOOT_WAIT_SECONDS)
        if msg is None:
            return "检索子进程预热超时或意外退出"
        if msg.get("type") == "ready":
            self._ready = True
            log.info("检索子进程预热完成（boot_ms=%s）", msg.get("boot_ms"))
            return None
        if msg.get("type") == "boot_error":
            self._boot_error = str(msg.get("error", "未知错误"))
            log.error("检索子进程预热失败: %s", self._boot_error)
            return self._boot_error
        return f"子进程启动消息异常: {msg}"

    # ---- 对外接口（阻塞，须在后台线程调用）----
    def search(self, query: str, top_k: int) -> dict:
        with self._lock:
            for attempt in (1, 2):  # 崩溃自动重启并重试一次
                err = self._ensure_ready()
                if err:
                    return {"ok": False, "error": err}
                try:
                    self._send({"cmd": "search", "query": query, "top_k": top_k})
                    msg = self._recv(timeout=_CALL_TIMEOUT_SECONDS)
                except Exception as e:
                    msg = None
                    log.warning("检索请求发送失败（第 %d 次）: %s", attempt, e)
                if msg and msg.get("ok") is not None:
                    return msg
                # 无有效响应 → 视为子进程异常，回收后重试
                log.warning("检索无有效响应（第 %d 次），回收子进程", attempt)
                self._kill()
            return {"ok": False, "error": "检索服务连续两次无响应，请查看服务日志"}

    def clear_cache(self):
        with self._lock:
            try:
                if self._proc and self._proc.poll() is None:
                    if self._ready:
                        self._send({"cmd": "clear_cache"})
                        self._recv(timeout=30)
            except Exception as e:
                log.warning("clear_cache 失败（不影响文档入库）: %s", e)

    def pre_spawn(self):
        """启动即拉起子进程（不等待预热），使其 7~10 秒的预热与用户打字并行。"""
        with self._lock:
            try:
                if self._proc is None or self._proc.poll() is not None:
                    self._spawn()
            except Exception as e:
                log.warning("预启动检索子进程失败（将在首次检索时重试）: %s", e)

    def _kill(self):
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.kill()
        except Exception:
            pass
        self._proc = None
        self._ready = False

    def shutdown(self):
        with self._lock:
            try:
                if self._proc and self._proc.poll() is None:
                    self._send({"cmd": "shutdown"})
                    self._proc.stdin.close()
                    self._proc.wait(timeout=10)
            except Exception:
                pass
            self._kill()


import queue  # noqa: E402

_WORKER = _WorkerManager()
atexit_registered = threading.Event()


def _register_atexit_once():
    if atexit_registered.is_set():
        return
    atexit_registered.set()
    import atexit
    atexit.register(_WORKER.shutdown)


mcp = FastMCP(
    name="enterprise-knowledge-base",
    instructions=(
        "企业私域知识库检索服务。"
        "当问题涉及企业内部制度、规章、产品手册、流程规范或专属业务知识时调用本服务。"
        "严禁用于解答公开互联网通识问题。"
    ),
)


@mcp.tool(
    description=(
        "在企业私域知识库中进行混合语义检索（向量召回 + BM25 关键词 + 重排精排）。"
        "适用于：查询公司内部制度（请假、年假、休假天数、考勤、报销、福利）、产品规范、操作手册、"
        "业务流程文档，以及任何存放在企业知识库中的私域文档内容。"
        "返回最相关的文档切片列表，包含来源文件名与匹配段落。"
    )
)
async def search_knowledge_base(
    query: Union[str, dict] = "",
    top_k: Union[int, str, dict] = 3,
    keyword: Union[str, dict] = ""
) -> str:
    """
    Args:
        query: 自然语言查询词，例如："差旅报销规定"、"年假申请流程"、"工龄6年休假天数"
        top_k: 返回的文档片段数量，默认 3，最多 8
        keyword: 兼容备用参数，同 query
    """
    # 彻底容错：自动解包各种大模型可能传入的嵌套字典（例如 {"query": {"query": "...", "top_k": 5}}, {"top_k": {"top_k": 5}}）
    search_text = ""
    parsed_top_k = 5

    # 1. 解包 query / keyword
    if isinstance(query, dict):
        search_text = query.get("query") or query.get("keyword") or query.get("text") or query.get("question") or ""
        if not search_text:
            for v in query.values():
                if isinstance(v, str) and v.strip():
                    search_text = v
                    break
        if "top_k" in query:
            parsed_top_k = query["top_k"]
    elif isinstance(query, str) and query.strip():
        search_text = query.strip()
    elif isinstance(keyword, dict):
        search_text = keyword.get("query") or keyword.get("keyword") or keyword.get("text") or ""
    elif isinstance(keyword, str) and keyword.strip():
        search_text = keyword.strip()

    # 2. 解包 top_k 参数本身
    if isinstance(top_k, dict):
        val = top_k.get("top_k") or top_k.get("k") or top_k.get("limit") or parsed_top_k
        parsed_top_k = val
    elif top_k not in (None, ""):
        parsed_top_k = top_k

    try:
        if isinstance(parsed_top_k, dict):
            for v in parsed_top_k.values():
                if isinstance(v, (int, str)):
                    parsed_top_k = v
                    break
        final_k = int(parsed_top_k)
    except (ValueError, TypeError):
        final_k = 5

    top_k = min(max(1, final_k), 10)
    query_str = str(search_text or "企业制度")

    _register_atexit_once()

    # 阻塞的子进程 I/O 放到后台线程，不阻塞事件循环；子进程预热未完成时在此等待
    result = await asyncio.to_thread(_WORKER.search, query_str, top_k)

    if not result.get("ok"):
        return (
            f"知识库引擎未就绪或检索失败：{result.get('error')}\n"
            "请检查 data/models 目录中的 BGE 模型与索引是否完整。"
        )

    docs = result.get("docs") or []
    if not docs:
        return (
            f"在企业知识库中未检索到与「{query_str}」相关的内容。\n"
            "建议：请确认知识库中已添加相关文档，或尝试换用其他关键词。"
        )

    lines = [f"## 知识库检索结果：「{query_str}」\n", f"共命中 {len(docs)} 个相关段落：\n"]
    for i, doc in enumerate(docs, 1):
        source = os.path.basename(doc.get("source") or "未知文档")
        content = (doc.get("content") or "").strip()
        if len(content) > 600:
            content = content[:600] + "...(已截断)"
        lines.append(f"### [{i}] 来源：{source}")
        lines.append(f"{content}\n")

    lines.append(f"（检索耗时 {result.get('elapsed_ms', '?')} ms）")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "列出企业知识库中当前已收录的所有文档及其基本信息（文件名、类型、大小）。"
        "当用户询问知识库里有哪些文件、已经录入了什么资料时调用。"
    )
)
def list_knowledge_documents() -> str:
    from config import folder_path
    if not os.path.isdir(folder_path):
        return f"文档目录不存在：{folder_path}"

    supported = {".pdf", ".docx", ".md", ".txt"}
    files = []
    for root, _, fnames in os.walk(folder_path):
        for fname in fnames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in supported:
                full = os.path.join(root, fname)
                size_kb = os.path.getsize(full) / 1024
                rel = os.path.relpath(full, folder_path)
                files.append((rel, ext.lstrip(".").upper(), round(size_kb, 1)))

    if not files:
        return (
            f"知识库文档目录为空。\n"
            f"请将文档（pdf/docx/md/txt）放入目录：{folder_path}\n"
            "或通过 add_document_to_knowledge 工具添加文档。"
        )

    lines = [f"## 企业知识库文档清单（共 {len(files)} 份）\n"]
    lines.append("| # | 文件名 | 类型 | 大小(KB) |")
    lines.append("|---|--------|------|----------|")
    for i, (name, ftype, size) in enumerate(sorted(files), 1):
        lines.append(f"| {i} | {name} | {ftype} | {size} |")
    lines.append(f"\n文档目录：{folder_path}")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "将本地文件（pdf/docx/md/txt）添加到企业知识库并触发增量向量索引更新。"
        "当用户说把这个文件加入知识库、新增一份制度文档时调用。"
        "file_path 必须是本地文件系统的绝对路径。"
    )
)
def add_document_to_knowledge(file_path: Union[str, dict] = "") -> str:
    """
    Args:
        file_path: 待添加文档的本地绝对路径
    """
    from config import folder_path

    if isinstance(file_path, dict):
        file_path = file_path.get("file_path") or file_path.get("path") or file_path.get("file") or ""
        if not file_path:
            for v in file_path.values():
                if isinstance(v, str) and v.strip():
                    file_path = v
                    break
    file_path = str(file_path or "").strip()

    if not os.path.isfile(file_path):
        return f"文件不存在：{file_path}\n请检查路径是否正确。"

    ext = os.path.splitext(file_path)[1].lower()
    supported = {".pdf", ".docx", ".md", ".txt"}
    if ext not in supported:
        return f"不支持的文件类型：{ext}\n目前支持：{', '.join(supported)}"

    fname = os.path.basename(file_path)
    dst = os.path.join(folder_path, fname)

    if os.path.exists(dst):
        base, ext2 = os.path.splitext(fname)
        import time
        fname = f"{base}_{int(time.time())}{ext2}"
        dst = os.path.join(folder_path, fname)

    try:
        shutil.copy2(file_path, dst)
    except Exception as e:
        return f"复制文件失败：{e}"

    # 通知检索子进程清理缓存（下次检索自动增量重建索引）
    try:
        _register_atexit_once()
        threading.Thread(target=_WORKER.clear_cache, daemon=True).start()
    except Exception:
        pass

    return (
        f"文档已成功添加到知识库！\n"
        f"- 文件名：{fname}\n"
        f"- 存入目录：{folder_path}\n\n"
        f"向量索引将在下次检索时自动增量更新。"
    )


if __name__ == "__main__":
    # 握手先行：本文件不加载任何重型 C 扩展（全部在 rag_worker.py 子进程的主线程
    # 加载），FastMCP 亚秒级就绪即启动 stdio 服务，工具立刻进入客户端快照。
    # 同时立即后台拉起检索子进程预热——与用户打字时间并行，首问检索零冷启动等待。
    threading.Thread(target=_WORKER.pre_spawn, daemon=True, name="rag-pre-spawn").start()
    mcp.run(transport="stdio")
