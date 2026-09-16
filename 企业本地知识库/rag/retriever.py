import os
import re
import pickle
import json
import hashlib
import hmac
import logging
import asyncio
import threading
from typing import List, Union, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from config import TOP_K_RECALL, LOCAL_DB_PATH, RERANK_LIMIT, CACHE_HMAC_KEY
from rag.vector_store import get_vector_store
from rag.rewriter import question_rewriter
from rag.reranker import reranker_doc as rerank_documents
from rag.dedup import deduplicate_docs

logger = logging.getLogger(__name__)

BM25_CACHE_PATH = os.path.join(LOCAL_DB_PATH, "bm25_cache.pkl")

# ==================== 优化点 (T8): BM25 磁盘缓存工厂 ====================
def get_or_build_bm25(documents: List[Document]) -> Union[BM25Retriever, None]:
    if not documents:
        return None
    try:
        # H2 修复：遍历所有文档片段并做摘要哈希组合，避免单一首文档误判断
        hasher = hashlib.md5()
        hasher.update(str(len(documents)).encode("utf-8"))
        for doc in documents:
            hasher.update(doc.page_content[:200].encode("utf-8", errors="replace"))
        doc_hash = hasher.hexdigest()
        
        if os.path.exists(BM25_CACHE_PATH):
            try:
                with open(BM25_CACHE_PATH, "rb") as f:
                    cache_bytes = f.read()
                cached = pickle.loads(cache_bytes)
                if isinstance(cached, dict) and cached.get("hash") == doc_hash:
                    # 修复 D：绑定序列化载荷字节内容的 HMAC-SHA256 签名与 `.sig` 兄弟文件校验
                    if CACHE_HMAC_KEY:
                        sig_path = BM25_CACHE_PATH + ".sig"
                        if not os.path.exists(sig_path):
                            raise ValueError("BM25 缓存签名文件缺失")
                        with open(sig_path, "r", encoding="utf-8") as sf:
                            sig_data = json.load(sf)
                        payload_hash = hashlib.sha256(cache_bytes).hexdigest()
                        expected = hmac.new(CACHE_HMAC_KEY.encode('utf-8'), payload_hash.encode('utf-8'), hashlib.sha256).hexdigest()
                        if not hmac.compare_digest(sig_data.get("sig", ""), expected):
                            raise ValueError("BM25 缓存 HMAC 签名校验失败")
                    logger.info("BM25 索引命中磁盘缓存，且载荷签名校验通过，已快速载入")
                    return cached["retriever"]
            except Exception as e:
                logger.warning(f"读取 BM25 磁盘缓存失败或校验未通过: {e}，将重新构建")

        logger.info("正在构建 BM25 关键词检索索引...")
        bm25_retriever = BM25Retriever.from_documents(documents)
        bm25_retriever.k = TOP_K_RECALL
        
        try:
            cache_payload = {"hash": doc_hash, "retriever": bm25_retriever}
            cache_bytes = pickle.dumps(cache_payload)
            with open(BM25_CACHE_PATH, "wb") as f:
                f.write(cache_bytes)
            if CACHE_HMAC_KEY:
                payload_hash = hashlib.sha256(cache_bytes).hexdigest()
                sig = hmac.new(CACHE_HMAC_KEY.encode('utf-8'), payload_hash.encode('utf-8'), hashlib.sha256).hexdigest()
                with open(BM25_CACHE_PATH + ".sig", "w", encoding="utf-8") as sf:
                    json.dump({"sig": sig}, sf)
            # 加强磁盘存储权限
            try:
                os.chmod(BM25_CACHE_PATH, 0o600)
            except Exception:
                pass
            logger.info("BM25 索引已被成功序列化缓存至本地磁盘（已附加载荷 HMAC 签名）")
        except Exception as e:
            logger.warning(f"写入 BM25 磁盘缓存失败: {e}")
            
        return bm25_retriever
    except Exception as e:
        logger.error(f"BM25 构建过程异常: {e}")
        return None

# ==================== 优化点 (T1): 惰性检索器初始化与单例缓存 ====================
_retriever_cache: Dict[str, Any] = {}
_retriever_lock = threading.Lock()

def get_retrievers() -> Tuple[Any, Any]:
    if "vector" not in _retriever_cache:
        with _retriever_lock:
            if "vector" not in _retriever_cache:
                db, docs = get_vector_store()
                _retriever_cache["vector"] = db.as_retriever(search_kwargs={"k": TOP_K_RECALL})
                _retriever_cache["bm25"] = get_or_build_bm25(docs)
    return _retriever_cache["vector"], _retriever_cache["bm25"]

# 兼容传统全局引用的 Lazy 代理
class _LazyRetrieverProxy:
    def invoke(self, query: str) -> List[Document]:
        vec_retriever, _ = get_retrievers()
        return vec_retriever.invoke(query)

class _LazyBM25Proxy:
    def invoke(self, query: str) -> List[Document]:
        _, bm25_retriever = get_retrievers()
        if bm25_retriever:
            return bm25_retriever.invoke(query)
        return []

zhaohui = _LazyRetrieverProxy()
bm25 = _LazyBM25Proxy()

# ==================== 规章相关性置信度门禁 ====================
def _filter_by_relevance(question: str, docs: List[Document]) -> List[Document]:
    """
    规章相关性置信度门禁：
    基于中文二元语法 (bi-grams) 结合停用词过滤，杜绝通用数学、技术与常识提问（如'不等式如何计算'）
    因单一泛词（如'计算'）误召回企业员工考勤或差旅规章的假阳性现象。
    """
    if not docs or not question:
        return docs

    STOP_BIGRAMS = {
        "如何", "怎么", "怎样", "什么", "为何", "哪个", "哪位", "哪儿", "哪里",
        "可以", "能否", "是否", "请问", "一下", "这个", "那个", "计算", "求解",
        "处理", "了解", "介绍", "告诉我", "有哪些", "帮我", "规则", "规定", "制度",
        "办法", "细则", "标准", "流程", "要求", "几天", "多少", "具体", "相关"
    }

    clean_q = ''.join(c for c in str(question).lower() if '\u4e00' <= c <= '\u9fff' or c.isalnum())
    if len(clean_q) < 2:
        return docs

    # 提取提问中的核心实质 2-gram 关键词
    substantive_bigrams = [
        clean_q[i:i+2] for i in range(len(clean_q) - 1)
        if clean_q[i:i+2] not in STOP_BIGRAMS
    ]

    # 若提问全部由停用词构成（如"请问一下具体规定"），则放行
    if not substantive_bigrams:
        return docs

    relevant_docs = []
    for doc in docs:
        content = ((doc.page_content or "") + " " + str(doc.metadata.get("source", ""))).lower()
        # 只要提问中的实质关键词有在文档正文或来源中命中，即判定为相关
        if any(bg in content for bg in substantive_bigrams):
            relevant_docs.append(doc)

    return relevant_docs

# ==================== 定义上下文格式化 ====================
def huidalaiyuan(docs: List[Document]) -> str:
    results = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get('source', '未知')
        content = doc.page_content
        results.append(f"[文档{i}] 来源: {source}\n{content}")
    return "\n\n".join(results)

# ==================== 检索召回逻辑 ====================
def retrieve_single(q: str) -> List[Document]:
    vec_retriever, bm25_retriever = get_retrievers()
    docs_vector = vec_retriever.invoke(q)
    docs_bm25 = bm25_retriever.invoke(q)[:6] if bm25_retriever else []
    
    for d in docs_vector:
        d.metadata["retriever"] = "vector"
    for d in docs_bm25:
        d.metadata["retriever"] = "bm25"
        
    return docs_vector + docs_bm25

executor = ThreadPoolExecutor(max_workers=5)

async def zhaohui_and_rerank(
    inputs: Union[Dict[str, Any], str],
    rerank_limit: int = RERANK_LIMIT,
    return_documents: bool = False,
    target_llm: Any = None
) -> Union[List[Document], str]:
    """
    接收用户问题，投机并行执行查询重写与基础召回，进行重排去重后返回结果。
    """
    if isinstance(inputs, dict):
        question = inputs['input']
        target_llm = inputs.get('target_llm', target_llm)
    elif isinstance(inputs, str):
        question = inputs
    else:
        raise TypeError("zhaohui_and_rerank 接收到的 inputs 类型不合法，须为 dict 或 str")
    
    is_local = False
    if target_llm:
        endpoint = str(getattr(target_llm, "openai_api_base", "") or getattr(target_llm, "base_url", ""))
        if "1234" in endpoint or "11434" in endpoint or "localhost" in endpoint or "127.0.0.1" in endpoint:
            is_local = True

    if is_local:
        # 本地模式直接双路混合极速召回（20ms），彻底免除 3~6 秒的重写 LLM 等待
        all_docs = await asyncio.to_thread(retrieve_single, question)
    else:
        rewriter_task = asyncio.create_task(question_rewriter(question, target_llm))
        original_retrieval_task = asyncio.to_thread(retrieve_single, question)
        
        queries, original_docs = await asyncio.gather(rewriter_task, original_retrieval_task)
        
        other_queries = [q for q in queries if q != question]
        if other_queries:
            other_results = await asyncio.to_thread(
                lambda: list(executor.map(retrieve_single, other_queries))
            )
            other_docs = [doc for sublist in other_results for doc in sublist]
            all_docs = original_docs + other_docs
        else:
            all_docs = original_docs

    all_docs = deduplicate_docs(all_docs)
    chongpaishuju = await asyncio.to_thread(rerank_documents, question, all_docs, rerank_limit)
    
    expanded_docs = []
    for doc in chongpaishuju:
        if 'dad_content' in doc.metadata:
            dad_doc = Document(
                page_content=doc.metadata['dad_content'],
                metadata=doc.metadata
            )
            expanded_docs.append(dad_doc)
        else:
            expanded_docs.append(doc)
            
    final_docs = deduplicate_docs(expanded_docs)
    final_docs = _filter_by_relevance(question, final_docs)
    if is_local:
        final_docs = final_docs[:2]
    
    if return_documents:
        return final_docs
    if not final_docs:
        return ""
    return huidalaiyuan(final_docs)