import os
import logging
import torch
from typing import List
from langchain_core.documents import Document
from config import TOP_K_RERANK

logger = logging.getLogger(__name__)

reranker = None

_reranker_disabled = False

def _ensure_reranker_loaded() -> None:
    global reranker, _reranker_disabled
    if _reranker_disabled or reranker is not None:
        return
    reranker_path = os.getenv('RERANKER_MODEL_PATH')
    if not reranker_path or not os.path.exists(reranker_path):
        logger.info("未配置有效的 RERANKER_MODEL_PATH，系统将直接使用混合检索召回结果并保留前置排名。")
        _reranker_disabled = True
        return
    try:
        from FlagEmbedding import FlagReranker
        if torch.cuda.is_available():
            reranker = FlagReranker(reranker_path, use_fp16=True)
            logger.info("BGE Reranker 模型使用 GPU (CUDA) 加载成功。")
        else:
            reranker = FlagReranker(reranker_path, use_fp16=False)
            logger.info("BGE Reranker 模型使用 CPU 加载成功。")
    except RuntimeError as e:
        if "out of memory" in str(e).lower() or "cuda" in str(e).lower():
            logger.warning("显存不足，BGE Reranker 正在安全降级到 CPU 加载...")
            torch.cuda.empty_cache()
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            reranker = FlagReranker(reranker_path, use_fp16=False)
            logger.info("BGE Reranker 降级到 CPU 加载完成。")
        else:
            logger.warning(f"BGE Reranker 加载失败: {e}，将降级跳过重排。")
            _reranker_disabled = True
    except Exception as e:
        logger.warning(f"BGE Reranker 初始化异常: {e}，将降级跳过重排。")
        _reranker_disabled = True

# ==================== 定义重排（Rerank）行为 ====================
def reranker_doc(question: str, docs: List[Document], reranker_limit: int = 60) -> List[Document]:
    _ensure_reranker_loaded()
    if len(docs) > reranker_limit:
        logger.warning(f"召回文档数({len(docs)})超出安全水位，触发 {reranker_limit} 强截断。")
        docs = docs[:reranker_limit]
        
    valid_docs = [doc for doc in docs if doc.page_content and doc.page_content.strip()]
    if not valid_docs:
        return []
        
    if reranker is None:
        return valid_docs[:TOP_K_RERANK]
        
    try:
        bei_pinfenshuju = [[question, doc.page_content] for doc in valid_docs]
        fenshu = reranker.compute_score(bei_pinfenshuju, max_length=512)
        fsandsjbangding = list(zip(fenshu, valid_docs))
        fsandsjbangding.sort(key=lambda x: x[0], reverse=True)
        chongpai = [doc for _, doc in fsandsjbangding[:TOP_K_RERANK]]
        return chongpai
    except Exception as e:
        logger.warning(f"BGE Reranker 计算异常 ({e})，降级使用召回前置结果")
        return valid_docs[:TOP_K_RERANK]

rerank_documents = reranker_doc
