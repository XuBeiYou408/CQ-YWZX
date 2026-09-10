"""
企业本地知识库 MCP Server
通过 stdio JSON-RPC 2.0 协议将知识库检索能力暴露给 WorkBuddy 等 AI 助手。

支持的 Tools：
  - search_knowledge_base     : 混合检索（向量 + BM25 + 重排精排）
  - list_knowledge_documents  : 列出当前知识库中所有已索引文档
  - add_document_to_knowledge : 向知识库新增并索引文档（支持 pdf/docx/md/txt）
"""

import os
import sys
import shutil
import asyncio
import logging
from typing import Union, Dict, Any, Optional

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

# ---------- 主线程预加载 RAG 检索器核心 ----------
# 关键架构防御：Windows 下严禁在 asyncio.to_thread 异步线程中动态 import PyTorch / OpenMP
# 否则会触发 OS Loader Lock 与 Python GIL 之间的死锁，导致工具调用完全卡死挂起
_rag_ready = False
_rag_error = None

try:
    from rag.retriever import get_retrievers, zhaohui_and_rerank
    get_retrievers()
    _rag_ready = True
except Exception as e:
    _rag_error = str(e)
    logging.exception("主线程预加载 RAG 引擎异常: %s", e)

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
    top_k: Union[int, str, dict] = 5,
    keyword: Union[str, dict] = ""
) -> str:
    """
    Args:
        query: 自然语言查询词，例如："差旅报销规定"、"年假申请流程"、"工龄6年休假天数"
        top_k: 返回的文档片段数量，默认 5，最多 10
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

    if not _rag_ready:
        if _rag_error:
            return f"知识库引擎未就绪：{_rag_error}\n请检查 data/models 目录中的 BGE 模型是否存在。"
        try:
            get_retrievers()
        except Exception as e:
            return f"知识库引擎初始化失败：{e}"

    try:
        docs = await zhaohui_and_rerank(query_str, return_documents=True)
        docs = docs[:top_k]

        if not docs:
            return (
                f"在企业知识库中未检索到与「{query_str}」相关的内容。\n"
                "建议：请确认知识库中已添加相关文档，或尝试换用其他关键词。"
            )

        lines = [f"## 知识库检索结果：「{query_str}」\n", f"共命中 {len(docs)} 个相关段落：\n"]
        for i, doc in enumerate(docs, 1):
            source = os.path.basename(doc.metadata.get("source", "未知文档"))
            content = doc.metadata.get("dad_content", doc.page_content).strip()
            if len(content) > 600:
                content = content[:600] + "...(已截断)"
            lines.append(f"### [{i}] 来源：{source}")
            lines.append(f"{content}\n")

        return "\n".join(lines)

    except Exception as e:
        logging.exception("search_knowledge_base 执行异常")
        return f"检索时发生内部错误：{e}"


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

    try:
        from rag import retriever as _ret_mod
        _ret_mod._retriever_cache.clear()
    except Exception:
        pass

    return (
        f"文档已成功添加到知识库！\n"
        f"- 文件名：{fname}\n"
        f"- 存入目录：{folder_path}\n\n"
        f"向量索引将在下次检索时自动增量更新。"
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    mcp.run(transport="stdio")
