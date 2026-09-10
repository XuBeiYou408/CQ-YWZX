import os
import shutil
import logging
from datetime import datetime
from typing import List, Dict, Any
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.schemas import APIResponse
from config import folder_path
from rag.vector_store import reload_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"

@router.get("", response_model=APIResponse)
def list_documents():
    """获取知识库目录中的全部文档列表及状态"""
    os.makedirs(folder_path, exist_ok=True)
    docs = []
    total_size = 0
    
    for root, _, files in os.walk(folder_path):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in ALLOWED_EXTENSIONS:
                full_path = os.path.join(root, file)
                try:
                    stat = os.stat(full_path)
                    total_size += stat.st_size
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    docs.append({
                        "name": file,
                        "type": ext.lstrip(".").upper(),
                        "size": _format_size(stat.st_size),
                        "size_bytes": stat.st_size,
                        "mtime": mtime,
                        "status": "已入库"
                    })
                except Exception as e:
                    logger.warning(f"获取文档信息失败 {file}: {e}")
                    
    docs.sort(key=lambda x: x.get("mtime", ""), reverse=True)
    
    return APIResponse(data={
        "documents": docs,
        "total_count": len(docs),
        "total_size": _format_size(total_size),
        "storage_path": folder_path
    })

@router.post("/upload", response_model=APIResponse)
async def upload_document(file: UploadFile = File(...)):
    """上传本地企业文档并触发解析与向量库增量构建"""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}。仅支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
        
    os.makedirs(folder_path, exist_ok=True)
    save_path = os.path.join(folder_path, filename)
    
    try:
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)
        file_size = len(content)
        logger.info(f"成功保存上传文档: {filename} ({_format_size(file_size)})")
    except Exception as e:
        logger.error(f"保存文档失败 {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"保存文件失败: {str(e)}")
        
    try:
        reload_vector_store()
        logger.info(f"文档 {filename} 已成功入库并建立向量索引")
    except Exception as e:
        logger.error(f"构建向量索引异常: {e}")
        return APIResponse(
            code=200,
            message="文件已保存，但向量索引更新中，请稍后刷新",
            data={"filename": filename, "status": "saved"}
        )
        
    return APIResponse(
        code=200,
        message=f"文档 {filename} 解析与向量入库完成！",
        data={
            "filename": filename,
            "type": ext.lstrip(".").upper(),
            "size": _format_size(file_size),
            "status": "已入库"
        }
    )

@router.delete("/{file_name}", response_model=APIResponse)
def delete_document(file_name: str):
    """删除知识库文档并重新同步向量索引"""
    target_path = os.path.join(folder_path, file_name)
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="文件不存在")
        
    try:
        os.remove(target_path)
        logger.info(f"已删除文件: {target_path}")
    except Exception as e:
        logger.error(f"删除文件失败 {target_path}: {e}")
        raise HTTPException(status_code=500, detail=f"删除文件失败: {str(e)}")
        
    try:
        reload_vector_store()
        logger.info("删除文档后向量数据库重建同步成功")
    except Exception as e:
        logger.warning(f"向量库同步警告: {e}")
        
    return APIResponse(message=f"文档 {file_name} 已成功删除并同步知识库")
