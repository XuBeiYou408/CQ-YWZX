"""
智审 (Doc-Agent) - 合同审查、起草与 Word 批注导出 API 路由
"""
import os
import json
import logging
import tempfile
import urllib.parse
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse

from app.schemas import (
    APIResponse,
    ContractReviewRequest,
    PrecedentSearchRequest,
    ContractExportRequest,
    ContractDraftRequest
)
from sample_contract import (
    SAMPLE_CONTRACT_TEXT,
    AGENT_CONTRACT_TEXT,
    SAMPLE_CONTRACTS,
    get_sample_contract_by_id,
)
from contract.precedents import PRECEDENTS_DATABASE, search_precedents
from contract.parser import parse_uploaded_file, detect_contract_type
from contract.engine import engine
from config import config   # /sample/list 里用到 config.AGENT_ENABLED，此前漏了这行 import

logger = logging.getLogger(__name__)
router = APIRouter()

def _sse_pack(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

@router.post("/upload", response_model=APIResponse)
async def upload_contract_file(file: UploadFile = File(...)):
    """
    支持用户上传任意 .docx, .pdf, .txt, .md 文件并秒级解析
    """
    try:
        content_bytes = await file.read()
        filename = file.filename or "uploaded_contract.txt"

        parsed = parse_uploaded_file(filename, content_bytes)
        logger.info(f"成功解析用户上传文件: {filename}, 字数: {parsed['char_count']}, 识别类型: {parsed['contract_type']}")

        return APIResponse(data=parsed)
    except Exception as e:
        logger.error(f"文件解析失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")

@router.get("/sample/list", response_model=APIResponse)
async def list_sample_contracts():
    """获取内置示例合同清单（供前端下拉列表选择）"""
    from contract.clause_splitter import split_clauses
    items = []
    for c in SAMPLE_CONTRACTS:
        text = c["text"].strip()
        clause_count = len(split_clauses(text))
        char_count = len(text)
        items.append({
            "id": c["id"],
            "name": c["name"],
            "desc": c["desc"],
            "badge": c.get("badge", ""),
            "contract_type": c["contract_type"],
            "char_count": char_count,
            "clause_count": clause_count,
            # 去除门槛要求：只要 Agent 启用，全量合同均触发 Agent 审查
            "agent_triggered": config.AGENT_ENABLED,
        })
    return APIResponse(data=items)


@router.get("/sample", response_model=APIResponse)
async def get_sample_contract(id: str = None, mode: str = None):
    """
    获取预设的示范合同
    id   ：合同标识（不传则取清单第一项，即软件定制开发合同 Agent 演示版）
    mode ：兼容旧参数，mode=small 等价于 id=dev_small
    """
    if id is None and mode == "small":
        id = "dev_small"

    entry = get_sample_contract_by_id(id) if id else None
    if entry is None and id:
        return APIResponse(code=404, message=f"未找到示例合同：{id}", data=None)
    if entry is None:
        entry = SAMPLE_CONTRACTS[0]

    text = entry["text"].strip()
    return APIResponse(data={
        "id": entry["id"],
        "title": entry["name"],
        "content": text,
        "char_count": len(text),
        "contract_type": entry["contract_type"],
        "client_role": entry.get("client_role", ""),
        "review_stance": entry.get("review_stance", ""),
        "mode": entry["id"],
    })

@router.get("/precedents", response_model=APIResponse)
async def list_precedents():
    """获取内置最高法指导案例库 (已扩充至 32 项)"""
    return APIResponse(data=PRECEDENTS_DATABASE)

@router.post("/precedents/search", response_model=APIResponse)
async def search_precedents_api(req: PrecedentSearchRequest):
    """动态扫描合同文本并检索最匹配判例"""
    res = search_precedents(req.keyword, top_k=req.top_k)
    return APIResponse(data=res)

@router.post("/review/stream")
async def review_contract_stream_endpoint(req: ContractReviewRequest):
    """
    核心 SSE 流式通用审查接口 (集成立场声明、框架四问与专项门禁)
    """
    logger.info(f"收到合同审查请求，字数: {len(req.contract_text)}，指定类型: {req.contract_type}，立场: {req.client_role} ({req.review_stance})")

    async def event_generator():
        async for frame in engine.stream_review(
            contract_text=req.contract_text,
            contract_type=req.contract_type,
            client_role=req.client_role or "中立合规把关",
            review_stance=req.review_stance or "对等平衡",
            focus_dimensions=req.focus_dimensions,
            model_name=req.model_name
        ):
            yield _sse_pack(frame)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.post("/generate-draft", response_model=APIResponse)
async def generate_draft_endpoint(req: ContractExportRequest):
    """生成合规修改后的合同初稿全文"""
    try:
        revised = await engine.generate_revised_draft(req.original_text, req.review_report)
        return APIResponse(data={"revised_contract": revised})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"初稿生成失败: {str(e)}")

@router.post("/draft/create", response_model=APIResponse)
async def create_new_contract_draft(req: ContractDraftRequest):
    """
    从零智能起草新合同初稿接口
    """
    try:
        draft = await engine.generate_new_draft(
            contract_type=req.contract_type,
            party_a=req.party_a,
            party_b=req.party_b,
            core_subject=req.core_subject,
            payment_terms=req.payment_terms or "按阶段验收付款",
            special_terms=req.special_terms or "",
            client_role=req.client_role or "甲方",
            model_name=req.model_name
        )
        return APIResponse(data={"draft_text": draft})
    except Exception as e:
        logger.error(f"从零起草合同失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"从零起草合同失败: {str(e)}")

def _cleanup_temp_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

@router.post("/export-docx")
async def export_annotated_docx_endpoint(req: ContractExportRequest, background_tasks: BackgroundTasks):
    """
    导出带有 Word 原生批注 (Comments) 与修改痕迹 (Track Changes) 的 .docx 文件
    """
    try:
        temp_fd, temp_path = tempfile.mkstemp(prefix="contract_annotated_", suffix=".docx")
        os.close(temp_fd)

        engine.export_annotated_docx(
            original_text=req.original_text,
            review_report=req.review_report,
            title=req.title or "合同审查审阅批注版",
            output_path=temp_path
        )

        background_tasks.add_task(_cleanup_temp_file, temp_path)

        safe_filename = f"{req.title or '合同审查审阅批注版'}.docx"
        encoded_filename = urllib.parse.quote(safe_filename)

        return FileResponse(
            path=temp_path,
            filename=safe_filename,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
            }
        )
    except Exception as e:
        logger.error(f"导出 Word 批注失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出 Word 批注失败: {str(e)}")
