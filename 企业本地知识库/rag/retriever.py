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
from config import TOP_K_RECALL, LOCAL_DB_PATH, RERANK_LIMIT, TOP_K_RERANK, CACHE_HMAC_KEY
from rag.vector_store import get_vector_store, get_db_generation
from rag.rewriter import question_rewriter
from rag.reranker import reranker_doc as rerank_documents, is_reranker_enabled
from rag.dedup import deduplicate_docs

logger = logging.getLogger(__name__)

BM25_CACHE_PATH = os.path.join(LOCAL_DB_PATH, "bm25_cache.pkl")

# ==================== 修复 K: BM25 中文分词 ====================
# 背景（实测）：langchain BM25Retriever 默认分词函数是 `text.split()`（按空格切），
# 中文整句会被切成**一个 token**——`"请假怎么审批"` -> `['请假怎么审批']`，
# 绝大多数文档都不含这个整词，于是 BM25 的"第 1~6 名"基本是任意顺序的噪声文档。
# 这解释了为什么此前"混合检索"里 BM25 一路既没被用上（被截断饿死）、偶尔被用上时又是噪音源。
# 修法：改用中文友好的分词——装了 jieba 就用 jieba，否则退化为"ASCII 词 + 中文二元组"，
# 不引入新依赖（一键安装脚本无需变更）。
BM25_TOKENIZER_TAG = "zh-bigram-v1"

def _zh_preprocess(text: str) -> List[str]:
    """中文分词：jieba（若可用）优先，否则 ASCII 词 + 中文二元组混合切分"""
    raw = str(text or "")
    if not raw.strip():
        return []
    try:
        import jieba  # 可选依赖：装了就用，没装走降级分支
        tokens = [t.strip().lower() for t in jieba.lcut(raw) if t.strip()]
        if tokens:
            return tokens
    except Exception:
        pass
    tokens = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", raw)]
    for seg in re.findall(r"[\u4e00-\u9fff]+", raw):
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens

# ==================== 优化点 (T8): BM25 磁盘缓存工厂 ====================
def get_or_build_bm25(documents: List[Document]) -> Union[BM25Retriever, None]:
    if not documents:
        return None
    try:
        # H2 修复：遍历所有文档片段并做摘要哈希组合，避免单一首文档误判断
        # 修复 K：把分词器版本一并纳入哈希，分词策略变更后旧缓存自动失效
        hasher = hashlib.md5()
        hasher.update(BM25_TOKENIZER_TAG.encode("utf-8"))
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

        logger.info("正在构建 BM25 关键词检索索引（中文分词已启用）...")
        bm25_retriever = BM25Retriever.from_documents(documents, preprocess_func=_zh_preprocess)
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
# 修复 H：缓存增加版本号（gen）。向量库增删改后 get_db_generation() 会推进，
# 本缓存随即判定过期并重建，杜绝"新入库文档检索不到、必须重启服务"的问题。
_retriever_cache: Dict[str, Any] = {}
_retriever_lock = threading.Lock()

def invalidate_retriever_cache() -> None:
    """显式失效检索器缓存（供外部在特殊场景主动调用；常规增删改由版本号自动兜底）"""
    with _retriever_lock:
        _retriever_cache.clear()
    logger.info("检索器单例缓存已显式失效，下次查询将基于最新向量库重建")

def get_retrievers() -> Tuple[Any, Any]:
    # 版本号先行读取：若读取之后又发生 reload，本轮缓存标记的是旧版本号，
    # 下次查询会再重建一次（多一次构建开销，但绝不返回过期数据）。
    gen = get_db_generation()
    if _retriever_cache.get("gen") != gen:
        with _retriever_lock:
            if _retriever_cache.get("gen") != gen:
                db, docs = get_vector_store()
                _retriever_cache["vector"] = db.as_retriever(search_kwargs={"k": TOP_K_RECALL})
                _retriever_cache["bm25"] = get_or_build_bm25(docs)
                _retriever_cache["gen"] = gen
                logger.info(f"检索器已基于向量库版本 v{gen} 重建完成（文档分块数 {len(docs)}）")
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

# ==================== 修复 I: 双路倒数排名融合 (RRF) ====================
# 背景：retrieve_single 返回顺序是「向量 top35 + BM25 top6」，而重排模型未启用时
# 下游直接 `valid_docs[:TOP_K_RERANK]` 截断，导致 BM25 命中的位次恒定落在 36 之后，
# **关键词通道一条都进不了最终上下文**（实测 8/8 个问题如此），"混合检索"名存实亡。
# 修法：重排不可用时改用 RRF（Reciprocal Rank Fusion）按通道内排名融合再截断，
# 让 BM25 的精确词面命中真正参与排序。纯本地、零依赖、结果确定。
RRF_K = 60

def _rrf_fuse(docs: List[Document], limit: int) -> List[Document]:
    """按 metadata['retriever'] 区分通道，用 1/(K+rank) 累加融合后取前 limit 条。

    注意：**必须先按内容聚合得分、再取唯一条目**。同一份文档可能同时被主问法
    （位次靠后）与口语归一化视角（位次第 1）召回到，若先做 (source, content) 去重，
    后出现的高排名副本会被丢弃，归一化视角的贡献随之消失（实测踩过这个坑）。
    """
    if not docs or limit <= 0:
        return []
    counters: Dict[str, int] = {}
    scores: Dict[Any, float] = {}
    store: Dict[Any, Document] = {}
    for d in docs:
        key = (str(d.metadata.get("source", "")), d.page_content)
        channel = str(d.metadata.get("retriever", "vector"))
        counters[channel] = counters.get(channel, 0) + 1
        scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + counters[channel])
        store.setdefault(key, d)
    ranked = sorted(store.keys(), key=lambda k: -scores[k])
    return [store[k] for k in ranked[:limit]]

# ==================== 修复 J: 口语化问法归一化 ====================
# 背景：员工提问常用口语（"能在家上班吗"），与制度书面用词零重合时会被
# 「向量排序不利 + 相关性门禁全砍」双重淘汰，最终 0 条。此处仅做**词面归一化**
# 并在门禁零命中时重试一次，既补上口语场景，又保留门禁防止跨领域误召回的作用。
_COLLOQUIAL_MAP = {
    "在家里上班": "远程办公",
    "在家上班": "远程办公",
    "在家办公": "远程办公",
    "在家工作": "远程办公",
    "家里办公": "远程办公",
    "居家办公": "远程办公",
    "远程上班": "远程办公",
    "居家": "远程办公",
    "不来公司": "远程办公",
    "不用来公司": "远程办公",
    "涨工资": "调薪",
    "涨薪": "调薪",
    "加薪": "调薪",
    "扣工资": "扣款",
    "罚款": "扣款",
    "走人": "辞职",
    "不干了": "辞职",
    "报账": "报销",
    "超时": "加班",
    "能休几天": "天数",
    "给多少钱": "标准",
    "发多少钱": "标准",
    "多久能休": "天数",
    "能不能": "可否",
    "咋办": "怎么办",
    "咋弄": "怎么办",
}

def _normalize_question(question: str) -> str:
    """把口语化表述替换为制度书面用词；无变化时原样返回。
    长词优先替换，避免"在家上班"被短词先切走。"""
    if not question:
        return question
    normalized = str(question)
    for term in sorted(_COLLOQUIAL_MAP, key=len, reverse=True):
        if term in normalized:
            target = _COLLOQUIAL_MAP[term]
            if target not in normalized:
                normalized = normalized.replace(term, target)
    return normalized

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

async def _finalize_docs(
    question: str,
    all_docs: List[Document],
    rerank_limit: int,
    is_local: bool,
    alt_question: str = None
) -> List[Document]:
    """统一收口：融合排序 -> 父块展开 -> 二次去重 -> 相关性门禁 -> 条数上限。

    融合策略（修复 I）：重排可用时交给 BGE 精排；不可用时（当前默认）
    改用 RRF 排名融合，避免"拼接后直接截断"把 BM25 通道整体饿死。
    门禁（修复 J3）：若存在口语归一化问法 alt_question，则"原问法或归一化问法
    任一命中即保留"（并集，保持原顺序）——否则会出现"用户换了口语说法，
    门禁拿原句去比对制度原文、把目标文档整条剔除"的漏检（实测
    「在家上班一周最多几天」被剔除，而规范化后的「远程办公一周最多几天」本可命中）。
    """
    if await asyncio.to_thread(is_reranker_enabled):
        all_docs = deduplicate_docs(all_docs)
        chongpaishuju = await asyncio.to_thread(rerank_documents, question, all_docs, rerank_limit)
    else:
        # RRF 路径不做预去重：同一文档在多路视角/双通道中重复出现时要累加得分，
        # 去重交给 _rrf_fuse 内部"聚合得分后取唯一"处理。
        chongpaishuju = _rrf_fuse(all_docs, TOP_K_RERANK)

    expanded_docs = []
    for doc in chongpaishuju:
        if 'dad_content' in doc.metadata:
            expanded_docs.append(Document(page_content=doc.metadata['dad_content'], metadata=doc.metadata))
        else:
            expanded_docs.append(doc)

    final_docs = deduplicate_docs(expanded_docs)

    gate_questions = [question]
    if alt_question and alt_question != question:
        gate_questions.append(alt_question)
    allowed = set()
    for gq in gate_questions:
        allowed.update(id(d) for d in _filter_by_relevance(gq, final_docs))
    final_docs = [d for d in final_docs if id(d) in allowed]

    if is_local:
        # 与 kb-tool 对齐：本地极速路径不再硬切到 2 条。
        # 说明：展开后的条目是**父块正文**（docx 约 700 字/条），而多个子块可能同属一个父块，
        # 因此 [:2] 实际是按"前 2 个唯一父块"截断。实测（7 个问题样本）：
        #   跨主题提问损失最明显——"公司的制度都有哪些"唯一父块 5 个被切到 2（丢 3），
        #   "绩效考核怎么算" 4→2（丢 2），"请假和报销"/"新员工入职要带什么" 3→2（丢 1）；
        #   单主题提问（含"公司晋升机制"）唯一父块本就 ≤2，不受影响。
        # 体量核算：5 个父块约 3.5K 字符（≈1.75K token），对本地上下文预算可承受；
        # kb-tool 在重排未启用时的有效返回条数同样是 TOP_K_RERANK(=5)。
        final_docs = final_docs[:TOP_K_RERANK]
    return final_docs

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

    # 修复 J2：把口语归一化问法作为**额外一路视角**参与召回（与云端"查询重写"同构，但零 LLM 成本）。
    # 起因：修复 J 的兜底只在"门禁后 0 条"时触发，若门禁后剩几条**不相关**结果就不会触发，
    # 长句式口语提问仍会漏（实测「我在家里上班的话每周最多可以几天」召不到目标文档）。
    # 单独打通道标记，使其在 RRF 融合中与主问法同等竞争，而不是被排在列表尾部饿死。
    normalized = _normalize_question(question)
    if normalized and normalized != question:
        norm_docs = await asyncio.to_thread(retrieve_single, normalized)
        for d in norm_docs:
            d.metadata["retriever"] = "norm_" + str(d.metadata.get("retriever", "vector"))
        all_docs = all_docs + norm_docs

    final_docs = await _finalize_docs(question, all_docs, rerank_limit, is_local, alt_question=normalized)

    # 修复 J：门禁零命中兜底——用口语归一化后的问法重试一次。
    # 仅在"一条都没有"时触发（正常路径零额外开销），且仍走同一套门禁，
    # 不放松防误召回标准。
    if not final_docs and normalized and normalized != question:
        retry_docs = await asyncio.to_thread(retrieve_single, normalized)
        final_docs = await _finalize_docs(normalized, retry_docs, rerank_limit, is_local)
        if final_docs:
            logger.info(f"门禁零命中，已用口语归一化问法重试命中：「{question}」->「{normalized}」")

    if return_documents:
        return final_docs
    if not final_docs:
        return ""
    return huidalaiyuan(final_docs)