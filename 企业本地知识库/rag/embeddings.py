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
                    model_name = os.getenv('BGE_MODEL_PATH', 'BAAI/bge-base-zh-v1.5')
            self.model = SentenceTransformer(model_name, device=self.device)
            logger.info(f"本地 BGE Embedding 模型已成功加载到内存中 (设备: {self.device}, 路径: {model_name})。")

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
