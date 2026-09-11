"""
确定性指标聚合计算、AI 战略内参合成引擎与标准 Word (.docx) 导出器
"""
import io
import json
import re
from datetime import datetime
from typing import Any, Dict, List
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from app.core.llm_client import generate_chat


# 销售梯队分类，五类互斥
_STATUS_BUCKETS = ("exceeded", "on_track", "at_risk", "blocked", "growing")


def _bucket_of(report: Dict[str, Any]) -> str:
    """
    将单份周报归入唯一梯队类别。
    以 status 为权威判据，缺失时按达成率推导，确保同一人不会被重复计数。
    """
    status = report.get("status")
    rate = report.get("completion_rate") or 0.0
    if status == "growing":
        return "growing"
    if status == "exceeded" or rate >= 100:
        return "exceeded"
    if status == "on_track" or rate >= 80:
        return "on_track"
    if status == "at_risk" or rate >= 50:
        return "at_risk"
    return "blocked"


def calculate_team_metrics(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    100% 确定性算术指标统计层（杜绝大模型数字幻觉）
    """
    if not reports:
        return {
            "total_target": 0.0,
            "total_actual": 0.0,
            "total_collection": 0.0,
            "overall_completion_rate": 0.0,
            "collection_rate": 0.0,
            "total_visits": 0,
            "total_leads": 0,
            "rep_count": 0,
            "exceeded_count": 0,
            "on_track_count": 0,
            "at_risk_count": 0,
            "blocked_count": 0,
            "growing_count": 0,
            "leaderboard": [],
        }

    total_target = sum(r.get("target_amount", 0.0) for r in reports)
    total_actual = sum(r.get("actual_amount", 0.0) for r in reports)
    total_collection = sum(r.get("collection_amount", 0.0) for r in reports)
    total_visits = sum(r.get("visit_count", 0) for r in reports)
    total_leads = sum(r.get("new_leads", 0) for r in reports)

    overall_rate = round((total_actual / total_target * 100), 1) if total_target > 0 else 0.0
    collection_rate = round((total_collection / total_actual * 100), 1) if total_actual > 0 else 0.0

    buckets = {key: 0 for key in _STATUS_BUCKETS}
    for report in reports:
        buckets[_bucket_of(report)] += 1
    exceeded = buckets["exceeded"]
    on_track = buckets["on_track"]
    at_risk = buckets["at_risk"]
    blocked = buckets["blocked"]
    growing = buckets["growing"]

    # 龙虎榜按签约额降序排
    sorted_reps = sorted(reports, key=lambda x: x.get("actual_amount", 0.0), reverse=True)
    leaderboard = []
    for idx, r in enumerate(sorted_reps, start=1):
        leaderboard.append({
            "rank": idx,
            "id": r.get("id", f"rep-{idx}"),
            "name": r.get("salesperson", "未知"),
            "department": r.get("department", ""),
            "actual_amount": r.get("actual_amount", 0.0),
            "target_amount": r.get("target_amount", 0.0),
            "completion_rate": r.get("completion_rate", 0.0),
            "status": r.get("status", "on_track"),
            "status_label": r.get("status_label", "稳步推进"),
            "highlight": r.get("highlight_summary", ""),
        })

    return {
        "total_target": total_target,
        "total_actual": total_actual,
        "total_collection": total_collection,
        "overall_completion_rate": overall_rate,
        "collection_rate": collection_rate,
        "total_visits": total_visits,
        "total_leads": total_leads,
        "rep_count": len(reports),
        "exceeded_count": exceeded,
        "on_track_count": on_track,
        "at_risk_count": at_risk,
        "blocked_count": blocked,
        "growing_count": growing,
        "leaderboard": leaderboard,
    }


FALLBACK_TITLE = "销售部每周运营汇总与管理决策内参"
FALLBACK_PERIOD = "2026年第36周 (08.31 - 09.04)"


def _trim_sentence(text: str, max_len: int) -> str:
    """把多行要点压成单行短句，供兜底内参引用"""
    cleaned = re.sub(r"^\d+[.、)）]\s*", "", (text or "").strip())
    cleaned = cleaned.replace("**", "").replace("\n", " ").strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip() + "…"
    return cleaned


def build_fallback_summary(reports: List[Dict[str, Any]], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    无大模型时的高保真确定性兜底内参。
    所有数字取自 metrics，定性内容取自各人周报，确保与页面大盘、导出文档永远一致。
    """
    rep_count = metrics.get("rep_count", 0)
    total_target = metrics.get("total_target", 0.0) / 10000
    total_actual = metrics.get("total_actual", 0.0) / 10000
    total_collection = metrics.get("total_collection", 0.0) / 10000
    rate = metrics.get("overall_completion_rate", 0.0)
    col_rate = metrics.get("collection_rate", 0.0)
    at_risk = metrics.get("at_risk_count", 0)
    blocked = metrics.get("blocked_count", 0)

    overview = (
        f"本周共汇总 {rep_count} 位销售人员的周报，团队目标 {total_target:.1f} 万元，"
        f"实际签约 {total_actual:.1f} 万元，整体达成率 {rate}%；"
        f"实际回款 {total_collection:.1f} 万元，回款率 {col_rate}%。"
        f"累计有效客拜 {metrics.get('total_visits', 0)} 家次，储备高意向线索 {metrics.get('total_leads', 0)} 条。"
    )
    if blocked or at_risk:
        overview += f"其中 {blocked} 人遇阻卡单、{at_risk} 人存在差距，需重点督导破局。"
    else:
        overview += "全员节奏平稳，无重大卡点。"

    highlights: List[str] = []
    for item in metrics.get("leaderboard") or []:
        if len(highlights) >= 3:
            break
        if item.get("status") not in ("exceeded", "on_track", "growing"):
            continue
        line = (
            f"**{item.get('name', '未知')}（{item.get('department', '')}）**："
            f"本周签约 {item.get('actual_amount', 0.0) / 10000:.1f} 万元，"
            f"达成率 {item.get('completion_rate', 0.0)}%（{item.get('status_label', '')}）"
        )
        detail = _trim_sentence(item.get("highlight", ""), 60)
        if detail:
            line += f"。{detail}"
        highlights.append(line)
    if not highlights:
        highlights.append("**本周暂无达标战报**：请先导入销售人员周报或等待业绩回填后再生成汇总。")

    risks: List[str] = []
    for report in reports:
        if _bucket_of(report) in ("blocked", "at_risk"):
            risks.append(
                f"**{report.get('salesperson', '未知')}（{report.get('department', '')}）"
                f"{report.get('status_label', '')}**：{_trim_sentence(report.get('blockers', ''), 80)}"
            )
    if not risks:
        risks.append("**整体风险可控**：本周无销售出现重大卡点或明显差距。")

    actions: List[str] = []
    for index, report in enumerate(reports, start=1):
        blockers = (report.get("blockers") or "").strip()
        if blockers and blockers != "无明显卡点，按计划推进":
            actions.append(
                f"**行动 {index}（{report.get('salesperson', '未知')}）**：针对「"
                f"{_trim_sentence(blockers, 50)}」，主管需协调资源并安排下周跟进督导。"
            )
    if not actions:
        actions.append("**行动 1**：本周无明显卡点，保持现有节奏并关注高意向商机转化。")

    return {
        "report_title": FALLBACK_TITLE,
        "cycle_period": FALLBACK_PERIOD,
        "executive_overview": overview,
        "highlights": highlights,
        "risk_radar": risks,
        "manager_action_items": actions,
    }


async def generate_ai_executive_summary(reports: List[Dict[str, Any]], metrics: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    认知层：基于确定性精确数据和原始定性事实，驱动 LLM 提炼高价值的主管决策内参
    """
    # 构造清晰的提示词上下文（卡点等长文本截断，控制输入规模）
    reps_summary = []
    for r in reports:
        reps_summary.append(
            f"【销售姓名】: {r.get('salesperson')}\n"
            f"- 所属部门: {r.get('department')}\n"
            f"- 目标金额: {r.get('target_amount', 0)/10000:.1f}万元 | 实际签约: {r.get('actual_amount', 0)/10000:.1f}万元 (达成率: {r.get('completion_rate', 0)}%)\n"
            f"- 实际回款: {r.get('collection_amount', 0)/10000:.1f}万元 | 拜访客户数: {r.get('visit_count', 0)}家\n"
            f"- 核心战报与成果: {_trim_sentence(r.get('highlight_summary', '正常推进'), 100)}\n"
            f"- 遇到阻碍与卡点求助: {_trim_sentence(r.get('blockers', '无明显卡点'), 120)}\n"
            f"- 下周工作规划: {_trim_sentence(r.get('next_week_plan', '继续跟进'), 100)}\n"
        )
    reps_text = "\n".join(reps_summary)

    system_prompt = (
        "你是一位深耕 B2B 行业 15 年的集团销售运营总监与商业智囊。\n"
        "你的任务是对各区域销售人员提交的周报进行全景商业洞察与汇总，输出一份结构严谨、直击业务本质的《销售部每周运营汇总与决策内参》。\n\n"
        "【撰写原则】：\n"
        "1. 严格使用给定的精确统计数据，禁止捏造数字；\n"
        "2. 亮点要体现标杆价值，不仅说成了多少钱，更要总结打法突破；\n"
        "3. 风险要敢于亮出死穴（如换届卡单、竞品低价、交付工期、资源争夺），给出定性风险等级；\n"
        "4. 管理者行动清单必须点对点、可落地（说明主管何时介入、协调哪位资源、带什么方案去见客户）；\n"
        "5. 必须严格以标准 JSON 格式返回，不要包含任何前缀或后缀说明；\n"
        "6. 语言务必精炼，每条亮点/风险/行动不超过 60 字，直接给出结论，不要输出推理过程。\n"
    )

    user_prompt = f"""
请基于以下本周销售部已验证的确定性指标和各销售提交的原始周报事实，生成本周管理决策内参：

【部门经营大盘数据（确定性计算）】：
- 团队总人数：{metrics.get('rep_count')} 人
- 本周总目标：{metrics.get('total_target', 0)/10000:.1f} 万元
- 实际总签约：{metrics.get('total_actual', 0)/10000:.1f} 万元 (全员达成率: {metrics.get('overall_completion_rate')}%)
- 实际总回款：{metrics.get('total_collection', 0)/10000:.1f} 万元 (回款率: {metrics.get('collection_rate')}%)
- 拜访总数：{metrics.get('total_visits')} 家 | 储备高意向线索：{metrics.get('total_leads')} 条
- 人员状态分布：超额冲顶 {metrics.get('exceeded_count')} 人，稳健推进 {metrics.get('on_track_count')} 人，遇阻卡单 {metrics.get('blocked_count')} 人，新人破局 {metrics.get('growing_count')} 人

【各销售代表周报原始事实】：
{reps_text}

【要求输出的 JSON 结构（每条不超过 60 字，2-3 条即可）】：
{{
  "report_title": "销售部本周运营汇总与管理决策内参",
  "cycle_period": "2026年第36周",
  "executive_overview": "120 字以内，点评目标达成率、回款质量及整体节奏",
  "highlights": ["**亮点标题**：标杆价值与打法突破", "..."],
  "risk_radar": ["**风险标题 (高危/中危)**：丢单卡点根因及影响", "..."],
  "manager_action_items": ["**行动 1（对象）**：主管督导动作与资源协调指令", "..."]
}}

请直接输出上述 JSON，不要输出任何推理过程、前缀或后缀说明。
"""

    try:
        raw_resp = await generate_chat(user_prompt, system_prompt, cfg, json_mode=True)
        # 清洗可能存在的 markdown 代码块包裹
        cleaned = re.sub(r"^```(?:json)?", "", raw_resp.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned.strip(), flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        required = ("report_title", "executive_overview", "highlights", "risk_radar", "manager_action_items")
        if not all(key in data for key in required):
            raise ValueError(f"大模型返回的 JSON 缺少必需字段: {required}")
        data["_generated_by"] = "ai"
        return data
    except Exception as exc:
        print(f"[SalesAgent] AI 决策内参生成失败，已降级为确定性兜底内参: {exc}")
        fallback = build_fallback_summary(reports, metrics)
        fallback["_generated_by"] = "fallback"
        return fallback


def _set_cell_background(cell, fill_color: str):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_color}"/>')
    tcPr.append(shd)


def generate_docx_report(summary: Dict[str, Any], metrics: Dict[str, Any], reports: List[Dict[str, Any]]) -> bytes:
    """
    生成标准企业级 Word (.docx) 销售周报汇总文档
    含：封面/标题、总体经营 KPI 表格、核心战报、风险雷达、主管派工赋能栏及销售明细附录
    """
    doc = Document()

    # 页面边距设为标准 1 英寸
    for section in doc.sections:
        section.top_margin = Inches(0.9)
        section.bottom_margin = Inches(0.9)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # 1. 标题
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run(summary.get("report_title", "销售部每周运营汇总与管理决策内参"))
    title_run.font.size = Pt(20)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(0x0f, 0x17, 0x2a)  # slate-900

    # 2. 副标题与元数据
    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    now_str = datetime.now().strftime("%Y-%m-%d")
    period = summary.get("cycle_period", "2026年第36周")
    sub_run = sub_p.add_run(f"报告周期：{period}   |   汇总编制日期：{now_str}   |   销售运营管理部")
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = RGBColor(0x64, 0x74, 0x8b)  # slate-500
    doc.add_paragraph()  # 间距

    # 3. 经营大盘核心指标表
    h1 = doc.add_heading(level=1)
    r1 = h1.add_run("一、 部门总体经营大盘看板 (确定性统计)")
    r1.font.bold = True
    r1.font.color.rgb = RGBColor(0x00, 0x6b, 0x58)  # primary green

    table = doc.add_table(rows=2, cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["签约总额", "团队业绩目标", "总体达成率", "实际回款总额", "客户拜访总量"]
    values = [
        f"{metrics.get('total_actual', 0)/10000:.1f} 万元",
        f"{metrics.get('total_target', 0)/10000:.1f} 万元",
        f"{metrics.get('overall_completion_rate', 0)}%",
        f"{metrics.get('total_collection', 0)/10000:.1f} 万元",
        f"{metrics.get('total_visits', 0)} 家次",
    ]

    for col_idx, h in enumerate(headers):
        cell = table.cell(0, col_idx)
        cell.text = h
        _set_cell_background(cell, "006B58")
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in p.runs:
            run.font.bold = True
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(0xff, 0xff, 0xff)

    for col_idx, v in enumerate(values):
        cell = table.cell(1, col_idx)
        cell.text = v
        _set_cell_background(cell, "F1F5F9")
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in p.runs:
            run.font.bold = True
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(0x0f, 0x17, 0x2a)

    doc.add_paragraph()  # 间距

    # 4. 总体态势评述
    h2 = doc.add_heading(level=1)
    r2 = h2.add_run("二、 部门经营态势综合述评")
    r2.font.bold = True
    r2.font.color.rgb = RGBColor(0x00, 0x6b, 0x58)

    overview_p = doc.add_paragraph()
    overview_run = overview_p.add_run(summary.get("executive_overview", ""))
    overview_run.font.size = Pt(10.5)
    overview_p.paragraph_format.line_spacing = 1.3

    # 5. 核心战报与亮点
    h3 = doc.add_heading(level=1)
    r3 = h3.add_run("三、 核心战报与重大突破 (Highlights)")
    r3.font.bold = True
    r3.font.color.rgb = RGBColor(0x00, 0x6b, 0x58)

    for hl in summary.get("highlights", []):
        p = doc.add_paragraph(style="List Bullet")
        # 清理 markdown **
        clean_text = hl.replace("**", "")
        p.add_run(clean_text)

    # 6. 风险雷达与丢单卡点预警
    h4 = doc.add_heading(level=1)
    r4 = h4.add_run("四、 重大卡点与风险预警雷达 (Risk & Blockers)")
    r4.font.bold = True
    r4.font.color.rgb = RGBColor(0xba, 0x1a, 0x1a)  # danger red

    for rk in summary.get("risk_radar", []):
        p = doc.add_paragraph(style="List Bullet")
        clean_text = rk.replace("**", "")
        p.add_run(clean_text)

    # 7. 主管赋能与派工行动清单
    h5 = doc.add_heading(level=1)
    r5 = h5.add_run("五、 销售主管重点督导与派工赋能指南 (Action Plan)")
    r5.font.bold = True
    r5.font.color.rgb = RGBColor(0x50, 0x39, 0xf6)  # AI purple

    for act in summary.get("manager_action_items", []):
        p = doc.add_paragraph(style="List Bullet")
        clean_text = act.replace("**", "")
        p.add_run(clean_text)

    # 8. 各销售代表明细台账附录
    h6 = doc.add_heading(level=1)
    r6 = h6.add_run("六、 附录：各销售代表本周提交明细台账")
    r6.font.bold = True
    r6.font.color.rgb = RGBColor(0x00, 0x6b, 0x58)

    rep_table = doc.add_table(rows=1 + len(reports), cols=6)
    rep_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    rep_headers = ["销售姓名", "所属区域/部门", "签约额(万)", "目标额(万)", "达成率", "主管批阅状态"]

    for col_idx, h in enumerate(rep_headers):
        cell = rep_table.cell(0, col_idx)
        cell.text = h
        _set_cell_background(cell, "006B58")
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in p.runs:
            run.font.bold = True
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0xff, 0xff, 0xff)

    for row_idx, r in enumerate(reports, start=1):
        row_cells = rep_table.rows[row_idx].cells
        row_cells[0].text = r.get("salesperson", "")
        row_cells[1].text = r.get("department", "")
        row_cells[2].text = f"{r.get('actual_amount', 0)/10000:.1f}"
        row_cells[3].text = f"{r.get('target_amount', 0)/10000:.1f}"
        row_cells[4].text = f"{r.get('completion_rate', 0)}%"
        row_cells[5].text = "已批阅" if r.get("reviewed") else "待批阅"
        bg_col = "FFFFFF" if row_idx % 2 == 1 else "F8FAFC"
        for c in row_cells:
            _set_cell_background(c, bg_col)
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in c.paragraphs[0].runs:
                run.font.size = Pt(9)

    doc_stream = io.BytesIO()
    doc.save(doc_stream)
    return doc_stream.getvalue()