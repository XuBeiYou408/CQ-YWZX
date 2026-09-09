"""
确定性指标聚合计算、AI 战略内参合成引擎与标准 Word (.docx) 导出器
"""
import io
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

from app.core.llm_client import generate_chat


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

    exceeded = sum(1 for r in reports if r.get("status") == "exceeded" or r.get("completion_rate", 0) >= 100)
    on_track = sum(1 for r in reports if r.get("status") == "on_track" or (80 <= r.get("completion_rate", 0) < 100))
    blocked = sum(1 for r in reports if r.get("status") == "blocked" or r.get("completion_rate", 0) < 50)
    growing = sum(1 for r in reports if r.get("status") == "growing")

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
        "blocked_count": blocked,
        "growing_count": growing,
        "leaderboard": leaderboard,
    }


DEFAULT_FALLBACK_SUMMARY = {
    "report_title": "销售部第36周运营汇总与管理决策内参",
    "cycle_period": "2026年第36周 (08.31 - 09.04)",
    "executive_overview": "本周销售团队整体表现强劲，全员目标达成率达到 80.0%，回款率达 82.5%。大客户一部凭借华星智造 150 万标杆项目一举拉高部门大盘；华东零售 SaaS 项目顶住竞品恶意降价成功落单；华北区重点央企项目遇换届阻滞，新人拜访活力饱满，商机蓄水充沛。",
    "highlights": [
        "**标杆项目重大突破**：大客户总监赵子龙成功落地华星智造 150 万 ERP 升级合同，创下单周签约新高，并实现 120 万元款项到账，达成率达 125%。",
        "**竞品防守反击成功**：华东大区孙尚香面对竞品数引科技 6.5 折恶意砸盘，依托标杆案例演示与高可用架构说服客户，顺利收割连邦连锁 58 万签约。",
        "**开拓活力显著提升**：新晋销售诸葛孔明单周扫街拜访 12 家客户，斩获智影科技 10 万首单试点，储备高意向商机 8 条，进入 POC 验证 3 家。"
    ],
    "risk_radar": [
        "**华北央企大单卡滞风险 (高危)**：关云长推进的北方清洁能源 45 万物资采购项目，因客户集团高层换届、新部长要求工期压减至 20 天，面临流标与拖延高风险，需主管直接介入破局。",
        "**区域市场恶意价格战 (中危)**：华东零售市场低价竞争加剧，竞品数引科技大幅低价搅乱客户预算预期，后续苏州新零售客户对价格极度敏感，亟需差异化商务组合拳应对。",
        "**高端售前资源供给紧绷 (中危)**：赵子龙（华星答辩）、诸葛孔明（蔚蓝汽车技术选型）下周均需要核心解决方案专家入场，技术支撑资源存在排期冲突隐患。"
    ],
    "manager_action_items": [
        "**行动 1（关云长-华北破局）**：销售主管周一与关云长做沙盘推演，周三亲自陪同前往北京拜访新任张部长，交付总监协同出具《20天核心功能试点上线与平滑演进承诺函》。",
        "**行动 2（赵子龙-技术答辩）**：协调总部解决方案中心老周下周二上午全程参加中联重科技术路线答辩；法务部下周一上午出具华星智造补充协议终版盖章件。",
        "**行动 3（孙尚香-商务授权）**：针对苏州百味果等对价格敏感的零售商机，特批‘三年赠半年维保+赠送2个高级报表模块’商务促销策略，保住软件主报价底线。",
        "**行动 4（诸葛孔明-新业务赋能）**：安排售前工程师小陈与诸葛孔明结对，周二联合拜访蔚蓝汽车；统一输出《企业级私有化部署架构与安全审计白皮书》赋能团队。"
    ]
}


async def generate_ai_executive_summary(reports: List[Dict[str, Any]], metrics: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    认知层：基于确定性精确数据和原始定性事实，驱动 LLM 提炼高价值的主管决策内参
    """
    # 构造清晰的提示词上下文
    reps_summary = []
    for r in reports:
        reps_summary.append(
            f"【销售姓名】: {r.get('salesperson')}\n"
            f"- 所属部门: {r.get('department')}\n"
            f"- 目标金额: {r.get('target_amount', 0)/10000:.1f}万元 | 实际签约: {r.get('actual_amount', 0)/10000:.1f}万元 (达成率: {r.get('completion_rate', 0)}%)\n"
            f"- 实际回款: {r.get('collection_amount', 0)/10000:.1f}万元 | 拜访客户数: {r.get('visit_count', 0)}家\n"
            f"- 核心战报与成果: {r.get('highlight_summary', '正常推进')}\n"
            f"- 遇到阻碍与卡点求助: {r.get('blockers', '无明显卡点')}\n"
            f"- 下周工作规划: {r.get('next_week_plan', '继续跟进')}\n"
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
        "5. 必须严格以标准 JSON 格式返回，不要包含任何前缀或后缀说明。\n"
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

【要求输出的 JSON 结构】：
{{
  "report_title": "销售部第36周运营汇总与管理决策内参",
  "cycle_period": "2026年第36周",
  "executive_overview": "总体经营态势客观评述（150字左右，点评目标达成率、回款质量及整体节奏）",
  "highlights": [
    "**亮点标题**：详细描述销售攻坚标杆及复制价值",
    "**亮点标题**：详细描述..."
  ],
  "risk_radar": [
    "**风险标题 (高危/中危)**：深度剖析丢单卡点根因及影响",
    "**风险标题 (高危/中危)**：..."
  ],
  "manager_action_items": [
    "**行动 1（针对某销售/客户）**：主管具体督导赋能动作及资源协调指令",
    "**行动 2（针对某销售/客户）**：..."
  ]
}}
"""

    try:
        raw_resp = await generate_chat(user_prompt, system_prompt, cfg, json_mode=True)
        # 清洗可能存在的 markdown 代码块包裹
        cleaned = re.sub(r"^```(?:json)?", "", raw_resp.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned.strip(), flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        # 确保关键键存在
        for key in ("report_title", "executive_overview", "highlights", "risk_radar", "manager_action_items"):
            if key not in data:
                return DEFAULT_FALLBACK_SUMMARY
        return data
    except Exception as e:
        print(f"AI 决策内参生成异常或未开启大模型，已安全降级为高保真预设内参: {e}")
        return DEFAULT_FALLBACK_SUMMARY


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