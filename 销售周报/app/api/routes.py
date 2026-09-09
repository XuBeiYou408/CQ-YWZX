"""
FastAPI 业务路由层 - 销售周报自动汇总智能体
"""
import copy
from datetime import datetime
from typing import Any, Dict, List, Optional
import urllib.parse

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import PlainTextResponse

from app.config import CLOUD_PRESETS, load_config, save_config
from app.core.aggregator import (
    DEFAULT_FALLBACK_SUMMARY,
    calculate_team_metrics,
    generate_ai_executive_summary,
    generate_docx_report,
)
from app.core.llm_client import get_model_status, test_cloud_connection
from app.core.parser import parse_weekly_report
from app.core.presets import PRESET_SALES_REPORTS

router = APIRouter()

# 运行时内存数据持久区
_runtime_reports: List[Dict[str, Any]] = []
_runtime_summary: Dict[str, Any] = copy.deepcopy(DEFAULT_FALLBACK_SUMMARY)
_initialized = False


def _ensure_init():
    global _initialized
    if not _initialized:
        _runtime_reports.extend(copy.deepcopy(PRESET_SALES_REPORTS))
        _initialized = True


def _get_reports() -> List[Dict[str, Any]]:
    _ensure_init()
    return _runtime_reports


# ---------------- 模型管理接口 ----------------

@router.get("/api/model/status")
async def api_model_status():
    cfg = load_config()
    status = await get_model_status(cfg)
    return {"ok": True, "data": status}


@router.post("/api/model/test")
async def api_model_test(body: dict):
    base_url = body.get("base_url", "").strip()
    api_key = body.get("api_key", "").strip()
    model_name = body.get("model_name", "").strip()
    timeout = int(body.get("timeout", 12))
    if not base_url or not api_key or not model_name:
        raise HTTPException(status_code=400, detail="base_url / api_key / model_name 不能为空")
    result = await test_cloud_connection(base_url, api_key, model_name, timeout)
    return {"ok": result["success"], "data": result}


@router.post("/api/model/switch")
async def api_model_switch(body: dict):
    cfg = load_config()
    provider = body.get("active_provider", "local")
    if provider not in ("local", "cloud"):
        raise HTTPException(status_code=400, detail="active_provider 必须为 local 或 cloud")
    cfg["active_provider"] = provider
    if "cloud_model" in body and isinstance(body["cloud_model"], dict):
        cfg["cloud_model"].update(body["cloud_model"])
    save_config(cfg)
    return {"ok": True, "data": {"active_provider": provider}}


@router.get("/api/model/presets")
def api_model_presets():
    return {"ok": True, "data": CLOUD_PRESETS}


# ---------------- 销售周报列表与详情接口 ----------------

@router.get("/api/reports")
def list_reports(status: str = "all", q: str = "", sort: str = "amount"):
    reports = _get_reports()
    res = list(reports)

    if status != "all":
        res = [r for r in res if r.get("status") == status]

    if q.strip():
        q_lower = q.lower()
        res = [
            r for r in res
            if q_lower in r.get("salesperson", "").lower()
            or q_lower in r.get("department", "").lower()
            or q_lower in r.get("highlight_summary", "").lower()
            or q_lower in r.get("blockers", "").lower()
        ]

    if sort == "amount":
        res = sorted(res, key=lambda r: r.get("actual_amount", 0.0), reverse=True)
    elif sort == "rate":
        res = sorted(res, key=lambda r: r.get("completion_rate", 0.0), reverse=True)
    elif sort == "visits":
        res = sorted(res, key=lambda r: r.get("visit_count", 0), reverse=True)

    counts = {
        "all": len(reports),
        "exceeded": sum(1 for r in reports if r.get("status") == "exceeded"),
        "on_track": sum(1 for r in reports if r.get("status") == "on_track"),
        "blocked": sum(1 for r in reports if r.get("status") == "blocked"),
        "growing": sum(1 for r in reports if r.get("status") == "growing"),
    }

    metrics = calculate_team_metrics(reports)
    return {
        "ok": True,
        "data": res,
        "counts": counts,
        "metrics": metrics,
    }


@router.get("/api/reports/{report_id}")
def get_report_detail(report_id: str):
    reports = _get_reports()
    target = next((r for r in reports if r.get("id") == report_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"周报 ID {report_id} 不存在")
    return {"ok": True, "data": target}


@router.get("/api/reports/{report_id}/raw")
def get_report_raw_content(report_id: str):
    reports = _get_reports()
    target = next((r for r in reports if r.get("id") == report_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="周报不存在")
    raw = target.get("raw_content", "")
    filename = f"{target.get('salesperson', 'sales')}_周报原件.txt"
    encoded_filename = urllib.parse.quote(filename)
    return PlainTextResponse(
        content=raw,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.post("/api/reports/upload")
async def upload_reports(files: List[UploadFile] = File(...)):
    reports = _get_reports()
    added_list = []
    errors = []

    for f in files:
        try:
            content_bytes = await f.read()
            parsed = parse_weekly_report(f.filename or "周报.docx", content_bytes)
            # 生成新 ID
            parsed["id"] = f"rep-up-{int(datetime.now().timestamp())}-{len(reports)+1}"
            parsed["avatar_bg"] = "bg-teal-600"
            reports.append(parsed)
            added_list.append(parsed)
        except Exception as e:
            errors.append({"filename": f.filename, "error": str(e)})

    return {
        "ok": True,
        "data": {
            "uploaded_count": len(added_list),
            "added": added_list,
            "errors": errors,
        },
    }


@router.post("/api/reports/{report_id}/review")
def review_report(report_id: str, body: dict):
    reports = _get_reports()
    target = next((r for r in reports if r.get("id") == report_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="周报不存在")

    comment = body.get("comment", "").strip()
    target["reviewed"] = True
    target["review_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    if comment:
        target["supervisor_comment"] = comment
    return {"ok": True, "data": target}


@router.delete("/api/reports/{report_id}")
def delete_report(report_id: str):
    reports = _get_reports()
    idx = next((i for i, r in enumerate(reports) if r.get("id") == report_id), -1)
    if idx == -1:
        raise HTTPException(status_code=404, detail="周报不存在")
    removed = reports.pop(idx)
    return {"ok": True, "data": {"deleted_id": report_id, "salesperson": removed.get("salesperson")}}


@router.post("/api/reports/reset")
def reset_reports():
    reports = _get_reports()
    reports.clear()
    reports.extend(copy.deepcopy(PRESET_SALES_REPORTS))
    global _runtime_summary
    _runtime_summary = copy.deepcopy(DEFAULT_FALLBACK_SUMMARY)
    return {"ok": True, "data": {"count": len(reports)}}


# ---------------- 汇总与决策内参接口 ----------------

@router.get("/api/summary")
def get_summary():
    reports = _get_reports()
    metrics = calculate_team_metrics(reports)
    return {
        "ok": True,
        "data": {
            "metrics": metrics,
            "summary": _runtime_summary,
        },
    }


@router.post("/api/summary/generate")
async def generate_summary():
    global _runtime_summary
    cfg = load_config()
    reports = _get_reports()
    metrics = calculate_team_metrics(reports)
    new_summary = await generate_ai_executive_summary(reports, metrics, cfg)
    _runtime_summary = new_summary
    return {
        "ok": True,
        "data": {
            "metrics": metrics,
            "summary": _runtime_summary,
        },
    }


@router.put("/api/summary")
def update_summary(body: dict):
    global _runtime_summary
    for k in ("report_title", "cycle_period", "executive_overview", "highlights", "risk_radar", "manager_action_items"):
        if k in body:
            _runtime_summary[k] = body[k]
    return {"ok": True, "data": _runtime_summary}


# ---------------- 导出接口 ----------------

@router.get("/api/export/docx")
def export_docx():
    reports = _get_reports()
    metrics = calculate_team_metrics(reports)
    docx_bytes = generate_docx_report(_runtime_summary, metrics, reports)

    filename = f"销售部周报运营汇总_{datetime.now().strftime('%Y%m%d')}.docx"
    encoded_filename = urllib.parse.quote(filename)

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/api/export/markdown")
def export_markdown():
    reports = _get_reports()
    metrics = calculate_team_metrics(reports)
    lines = [
        f"# {_runtime_summary.get('report_title', '销售部每周运营汇总与决策内参')}",
        f"> **报告周期**：{_runtime_summary.get('cycle_period', '')} | **导出日期**：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 一、 部门核心经营数据大盘",
        f"- **总签约额**：{metrics.get('total_actual', 0)/10000:.1f} 万元 / 目标 {metrics.get('total_target', 0)/10000:.1f} 万元 (达成率: {metrics.get('overall_completion_rate')}%)",
        f"- **实际总回款**：{metrics.get('total_collection', 0)/10000:.1f} 万元 (回款率: {metrics.get('collection_rate')}%)",
        f"- **客户拜访总量**：{metrics.get('total_visits')} 家次 | **储备高意向线索**：{metrics.get('total_leads')} 条",
        f"- **销售人员分布**：超额冲顶 {metrics.get('exceeded_count')} 人，稳步推进 {metrics.get('on_track_count')} 人，遇阻卡单 {metrics.get('blocked_count')} 人",
        "",
        "## 二、 部门经营态势述评",
        _runtime_summary.get("executive_overview", ""),
        "",
        "## 三、 核心战报与重大突破 (Highlights)",
    ]
    for hl in _runtime_summary.get("highlights", []):
        lines.append(f"- {hl}")

    lines.extend([
        "",
        "## 四、 重大卡点与风险雷达 (Risk Radar)",
    ])
    for rk in _runtime_summary.get("risk_radar", []):
        lines.append(f"- {rk}")

    lines.extend([
        "",
        "## 五、 销售主管重点督导与派工清单 (Action Plan)",
    ])
    for act in _runtime_summary.get("manager_action_items", []):
        lines.append(f"- {act}")

    lines.extend([
        "",
        "## 六、 各销售代表周报明细台账",
        "| 销售姓名 | 所属部门 | 签约额(万) | 目标(万) | 达成率 | 核心战报 | 阻碍与求助 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])
    for r in reports:
        lines.append(
            f"| {r.get('salesperson')} | {r.get('department')} | "
            f"{r.get('actual_amount', 0)/10000:.1f} | {r.get('target_amount', 0)/10000:.1f} | "
            f"{r.get('completion_rate')}% | {r.get('highlight_summary', '')} | {r.get('blockers', '')} |"
        )

    md_content = "\n".join(lines)
    filename = f"销售部周报汇总_{datetime.now().strftime('%Y%m%d')}.md"
    encoded_filename = urllib.parse.quote(filename)
    return PlainTextResponse(
        content=md_content,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )