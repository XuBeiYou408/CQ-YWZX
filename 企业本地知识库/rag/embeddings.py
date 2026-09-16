import os
import logging
import torch
from typing import List, Optional
from langchain_core.embeddings import Embeddings
from config import EMBEDDING_BATCH_SIZE

logger = logging.getLogger(__name__)

class BGEEmbeddings(Embeddings):
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def _ensure_model_loaded(self) -> None:
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            model_name = self.model_name
            if model_name is None:
                local_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'models', 'bge-base-zh-v1.5'))
                if os.path.isdir(local_dir):
                    model_name = local_dir
                else:
                    env_model = os.getenv('BGE_MODEL_PATH')
                    if env_model and os.path.isdir(env_model):
                        model_name = os.path.abspath(env_model)
                    else:
                        model_name = 'BAAI/bge-base-zh-v1.5'
            try:
                self.model = SentenceTransformer(model_name, device=self.device)
                logger.info(f"本地 BGE Embedding 模型已成功加载到内存中 (设备: {self.device}, 路径: {model_name})。")
            except Exception as e:
                err_msg = str(e)
                if "huggingface.co" in err_msg or "offline" in err_msg.lower() or "not find" in err_msg.lower():
                    raise RuntimeError(
                        f"无法加载 BGE 嵌入模型（目标路径: '{model_name}'）。\n"
                        f"【排查建议】：\n"
                        f"1. 离线部署环境：请确认已将模型权重放置于项目 'data/models/bge-base-zh-v1.5' 目录下；\n"
                        f"2. 在线自动下载：请检查当前机器网络是否通畅（系统已默认配置国内镜像源 https://hf-mirror.com）。\n"
                        f"底包错误: {err_msg}"
                    ) from e
                raise

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        优化点 (T6)：分批推理，防止全量构建时因一次性送入数百个长文本导致 VRAM OOM
        """
        self._ensure_model_loaded()
        all_embeddings: List[List[float]] = []
        batch_size = EMBEDDING_BATCH_SIZE
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embs = self.model.encode(
                batch, normalize_embeddings=True, show_progress_bar=False
            )
            all_embeddings.extend(batch_embs.tolist())
            
        # R2-L4 修复：在全部批次推理完成后清理一次，避免循环内强制 GPU-CPU 流同步造成性能损耗
        if self.device == "cuda":
            torch.cuda.empty_cache()
                
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        self._ensure_model_loaded()
        return self.model.encode([text], normalize_embeddings=True)[0].tolist()

embeddings = BGEEmbeddings()
