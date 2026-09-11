"""
FastAPI 业务路由层 - 销售周报自动汇总智能体 (v2.0 复合智能体 + SQLite 强闭环持久化)
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import urllib.parse

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import PlainTextResponse

from app.config import CLOUD_PRESETS, load_config, save_config
from app.core import database as db
from app.core.aggregator import (
    build_fallback_summary,
    calculate_team_metrics,
    generate_ai_executive_summary,
    generate_docx_report,
)
from app.core.llm_client import generate_chat, get_model_status, test_cloud_connection
from app.core.parser import parse_weekly_report
from app.core.screening import run_report_screening_pipeline

router = APIRouter()


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
    if not base_url or not model_name:
        raise HTTPException(status_code=400, detail="Base URL 与模型名称不能为空")
    res = await test_cloud_connection(base_url, api_key, model_name)
    return {"ok": True, "data": res}


@router.post("/api/model/config")
def api_save_model_config(body: dict):
    provider = body.get("provider", "lm_studio")
    cfg = load_config()
    cfg["provider"] = provider
    if "base_url" in body:
        cfg["cloud_base_url"] = body["base_url"].strip()
    if "api_key" in body and body["api_key"].strip():
        cfg["cloud_api_key"] = body["api_key"].strip()
    if "model_name" in body:
        cfg["cloud_model"] = body["model_name"].strip()
    if "cloud_provider" in body:
        cfg["cloud_provider"] = body["cloud_provider"].strip()
    save_config(cfg)
    return {"ok": True, "data": {"saved": True, "provider": provider}}


@router.get("/api/model/presets")
def api_get_cloud_presets():
    return {"ok": True, "data": CLOUD_PRESETS}


# ---------------- 周报管理接口 ----------------

@router.get("/api/reports")
def get_reports(status: str = "all", q: str = "", sort: str = "default"):
    reports = db.get_all_reports()
    res = reports

    if status != "all":
        res = [r for r in res if r.get("status") == status]

    if q:
        q_lower = q.lower().strip()
        res = [
            r
            for r in res
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

    metrics = calculate_team_metrics(reports)
    counts = {
        "all": metrics["rep_count"],
        "exceeded": metrics["exceeded_count"],
        "on_track": metrics["on_track_count"],
        "at_risk": metrics["at_risk_count"],
        "blocked": metrics["blocked_count"],
        "growing": metrics["growing_count"],
    }
    return {
        "ok": True,
        "data": res,
        "counts": counts,
        "metrics": metrics,
    }


@router.get("/api/reports/{report_id}")
def get_report_detail(report_id: str):
    target = db.get_report_by_id(report_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"周报 ID {report_id} 不存在")
    return {"ok": True, "data": target}


@router.get("/api/reports/{report_id}/raw")
def get_report_raw_content(report_id: str):
    target = db.get_report_by_id(report_id)
    if not target:
        raise HTTPException(status_code=404, detail="周报不存在")
    raw = target.get("raw_content", "")
    suffix = ".md" if Path(target.get("filename", "")).suffix.lower() == ".md" else ".txt"
    filename = f"{target.get('salesperson', 'sales')}_周报原件{suffix}"
    encoded_filename = urllib.parse.quote(filename)
    return PlainTextResponse(
        content=raw,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.post("/api/reports/upload")
async def upload_reports(files: List[UploadFile] = File(...)):
    existing_reports = db.get_all_reports()
    cfg = load_config()
    added_list = []
    errors = []

    for f in files:
        try:
            content_bytes = await f.read()
            parsed = parse_weekly_report(f.filename or "周报.docx", content_bytes)
            parsed["id"] = f"rep-up-{int(datetime.now().timestamp())}-{len(existing_reports)+len(added_list)+1}"
            parsed["avatar_bg"] = "bg-teal-600"
            # 运行 L1 极速守门员与 L2 智能体深度穿透
            await run_report_screening_pipeline(parsed, cfg=cfg)
            added_list.append(parsed)
        except Exception as e:
            errors.append({"filename": f.filename, "error": str(e)})

    # 持久化落盘并联动更新内参大盘
    if added_list:
        db.save_reports_batch(added_list)
        db.sync_summary_on_upload(len(added_list))

    return {
        "ok": True,
        "data": {
            "uploaded_count": len(added_list),
            "added": added_list,
            "errors": errors,
        },
    }


@router.post("/api/reports/{report_id}/deep-audit")
async def deep_audit_report(report_id: str):
    """
    单人即时重新触发 ReAct 智能体深度督导审计并原子落盘
    """
    target = db.get_report_by_id(report_id)
    if not target:
        raise HTTPException(status_code=404, detail="周报不存在")
    cfg = load_config()
    await run_report_screening_pipeline(target, cfg=cfg)
    updated = db.update_report_audit(
        report_id,
        target.get("supervision_audit", {}),
        target.get("hard_gate", {})
    )
    return {"ok": True, "data": updated or target}


@router.post("/api/reports/{report_id}/review")
def review_report(report_id: str, body: dict):
    target = db.get_report_by_id(report_id)
    if not target:
        raise HTTPException(status_code=404, detail="周报不存在")

    comment = body.get("comment", "").strip()
    review_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    updated = db.update_report_review(report_id, comment, review_time)
    return {"ok": True, "data": updated or target}


@router.post("/api/reports/reset")
def reset_reports():
    count = db.reset_to_presets()
    return {"ok": True, "data": {"count": count}}


# ---------------- 宏观全景动态诊断接口 (方案 B) ----------------

@router.get("/api/diagnostics")
async def run_diagnostics():
    """
    AI 销售战区经营全景动态诊断引擎
    结合在池全员真实尽调数据，动态加权计算健康度、真实置信度与 4 维战略决策内参，并持久化缓存
    """
    cfg = load_config()
    reports = db.get_all_reports()
    metrics = calculate_team_metrics(reports)
    total = len(reports)

    if total == 0:
        diag_empty = {
            "health_score": 60,
            "confidence_rate": 0,
            "risk_exposure": 0,
            "total_reps": 0,
            "high_confidence_count": 0,
            "at_risk_count": 0,
            "strategy_insights": ["当前战区暂无周报样本，建议导入销售周报数据进行推演。"],
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        db.save_diagnostics(diag_empty)
        return {"ok": True, "data": diag_empty}

    # 动态加权计算置信度
    scores = [r.get("supervision_audit", {}).get("confidence_score", 70) for r in reports]
    avg_confidence = round(sum(scores) / total, 1)

    high_conf_reps = [r for r in reports if r.get("supervision_audit", {}).get("confidence_score", 70) >= 70]
    high_conf_count = len(high_conf_reps)

    blocked_or_cliff = [
        r for r in reports
        if r.get("supervision_audit", {}).get("audit_badge") in ("🚨 致命卡单", "⚠️ 断崖预警", "⛔ 合规拦截")
        or r.get("status") in ("blocked", "at_risk")
    ]
    at_risk_count = len(blocked_or_cliff)
    risk_exposure = round((at_risk_count / total) * 100)

    # 战区综合健康评分 (0 - 100)
    comp_rate = min(120.0, metrics.get("overall_completion_rate", 0.0))
    health_score = int(avg_confidence * 0.45 + (comp_rate / 120.0) * 35 + (100 - risk_exposure) * 0.2)
    health_score = max(45, min(98, health_score))

    # 构建在池销售真实动态档案物料
    roster_lines = []
    for r in reports:
        name = r.get("salesperson", "未知")
        dept = r.get("department", "")
        rate = r.get("completion_rate", 0)
        badge = r.get("supervision_audit", {}).get("audit_badge", "✓ 稳步推进")
        conf = r.get("supervision_audit", {}).get("confidence_score", 70)
        roster_lines.append(f"- {name}（{dept}）：达成率 {rate}%，尽调状态【{badge}】，真实置信度 {conf}%")

    roster_text = "\n".join(roster_lines)

    insights = [
        "【标杆战法复制】KA 大客户攻坚战役打法已被验证高可信，建议将其供应链协同与高层公关路径沉淀为标准打法，在华东、华北跨区推广。",
        f"【卡单止血排雷】大盘存在 {at_risk_count} 处重大卡点异动（含体制换届卡单与竞品低价恶意围标），建议主管针对性协同法务与高管亲自下场陪访破局。",
        "【商机蓄水扩容】华北大区过程拜访与新增线索存在下滑迹象，需强化商机蓄水池复盘，严防下月业绩断崖式下行。",
        "【高管资源协同】战略创新业务与新人团队拜访密度充沛，需加派总部技术专家与解决方案架构师给予售前资源兜底支持。"
    ]

    try:
        diag_prompt = f"""作为集团销售高级副总裁与战略顾问，请基于以下战区当前全员真实尽调数据（总人数: {total}人，健康评分: {health_score}分，平均置信度: {avg_confidence}%，高风险暴露率: {risk_exposure}%）：
{roster_text}

请严格输出 4 维精炼战略督导建议（每条 60-80 字，必须带【】标题）：
1. 【标杆战法复制】：如何提炼头部成功路径并复制；
2. 【卡单止血排雷】：针对卡单/丢单死穴的止血指令；
3. 【商机蓄水扩容】：针对断崖风险大区的蓄水促活；
4. 【高管资源协同】：集团管理层下周出差与资源调配指令。
不要包含任何其他多余文本或推理。"""
        ai_resp = await generate_chat(diag_prompt, "你是一位洞察极其深邃的集团销售运营总监与商业智囊。", cfg)
        if ai_resp:
            lines = [l.strip() for l in ai_resp.split("\n") if l.strip() and ("【" in l or l.startswith("-") or l.startswith("1") or l.startswith("2") or l.startswith("3") or l.startswith("4"))]
            if len(lines) >= 3:
                insights = lines[:4]
    except Exception:
        pass

    diag_result = {
        "health_score": health_score,
        "confidence_rate": avg_confidence,
        "risk_exposure": risk_exposure,
        "total_reps": total,
        "high_confidence_count": high_conf_count,
        "at_risk_count": at_risk_count,
        "strategy_insights": insights,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    db.save_diagnostics(diag_result)

    return {
        "ok": True,
        "data": diag_result
    }


# ---------------- 汇总与决策内参接口 ----------------

@router.get("/api/summary")
def get_summary():
    reports = db.get_all_reports()
    metrics = calculate_team_metrics(reports)
    summary = db.get_latest_summary()
    return {
        "ok": True,
        "data": {
            "metrics": metrics,
            "summary": summary,
        },
    }


@router.post("/api/summary/generate")
async def generate_summary():
    cfg = load_config()
    reports = db.get_all_reports()
    metrics = calculate_team_metrics(reports)
    new_summary = await generate_ai_executive_summary(reports, metrics, cfg)
    saved_summary = db.save_summary(new_summary)
    return {
        "ok": True,
        "data": {
            "metrics": metrics,
            "summary": saved_summary,
        },
    }


@router.put("/api/summary")
def update_summary(body: dict):
    current = db.get_latest_summary()
    for k in ("report_title", "cycle_period", "executive_overview", "highlights", "risk_radar", "manager_action_items"):
        if k in body:
            current[k] = body[k]
    saved = db.save_summary(current)
    return {"ok": True, "data": saved}


# ---------------- 导出接口 ----------------

@router.get("/api/export/docx")
def export_docx():
    reports = db.get_all_reports()
    metrics = calculate_team_metrics(reports)
    summary = db.get_latest_summary()
    doc_bytes = generate_docx_report(summary, metrics, reports)
    filename = f"销售部周报汇总_{datetime.now().strftime('%Y%m%d')}.docx"
    encoded_filename = urllib.parse.quote(filename)
    return Response(
        content=doc_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )


@router.get("/api/export/markdown")
def export_markdown():
    reports = db.get_all_reports()
    metrics = calculate_team_metrics(reports)
    summary = db.get_latest_summary()
    lines = [
        f"# {summary.get('report_title', '销售部每周运营汇总与决策内参')}",
        f"> **报告周期**：{summary.get('cycle_period', '')} | **导出日期**：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 一、 部门核心经营数据大盘",
        f"- **总签约额**：{metrics.get('total_actual', 0)/10000:.1f} 万元 / 目标 {metrics.get('total_target', 0)/10000:.1f} 万元 (达成率: {metrics.get('overall_completion_rate')}%)",
        f"- **实际总回款**：{metrics.get('total_collection', 0)/10000:.1f} 万元 (回款率: {metrics.get('collection_rate')}%)",
        f"- **客户拜访总量**：{metrics.get('total_visits')} 家次 | **储备高意向线索**：{metrics.get('total_leads')} 条",
        f"- **销售人员分布**：超额冲顶 {metrics.get('exceeded_count')} 人，稳步推进 {metrics.get('on_track_count')} 人，遇阻卡单 {metrics.get('blocked_count')} 人",
        "",
        "## 二、 部门经营态势述评",
        summary.get("executive_overview", ""),
        "",
        "## 三、 核心战报与重大突破 (Highlights)",
    ]
    for hl in summary.get("highlights", []):
        lines.append(f"- {hl}")

    lines.extend([
        "",
        "## 四、 重大卡点与风险雷达 (Risk Radar)",
    ])
    for rk in summary.get("risk_radar", []):
        lines.append(f"- {rk}")

    lines.extend([
        "",
        "## 五、 销售主管重点督导与派工清单 (Action Plan)",
    ])
    for act in summary.get("manager_action_items", []):
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
