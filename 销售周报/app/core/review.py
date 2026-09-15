"""
主管批阅建议规则引擎（0 Token 确定性）

为批阅工作台提供：
  1) 风险分级 assess_review_risk：基于尽调徽章/状态/置信度把每份周报划入 0-4 风险级；
  2) 批语草稿 build_suggested_comment：按风险级与指标生成可直接下发的批阅建议。
全部为确定性规则，不消耗任何 LLM Token；AI 增强批语以本引擎输出为兜底。
"""
from typing import Any, Dict


def _summarize(text: str, max_len: int = 60) -> str:
    text = (text or "").strip().replace("\n", "；")
    return text[:max_len] + ("…" if len(text) > max_len else "")


def assess_review_risk(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    风险分级（数字越大越紧急）：
      4 🚨 紧急介入：致命卡单 / 合规拦截
      3 ⚠️ 高风险：断崖预警 / 遇阻预警
      2 🔶 需关注：存在差距 / 置信度 < 60
      1 🌟 亮眼：超额完成且尽调可信
      0 ✓ 正常推进
    """
    audit = report.get("supervision_audit") or {}
    badge = audit.get("audit_badge", "") or ""
    confidence = audit.get("confidence_score", 70) or 70
    status = report.get("status", "")
    rate = report.get("completion_rate", 0) or 0

    if "致命" in badge or "合规拦截" in badge:
        return {"level": 4, "label": "🚨 紧急介入", "reason": f"尽调徽章：{badge}"}
    if "断崖" in badge:
        return {"level": 3, "label": "⚠️ 断崖风险", "reason": f"尽调徽章：{badge}"}
    if status == "blocked":
        return {"level": 3, "label": "⚠️ 遇阻卡单", "reason": "达成率过低，触发遇阻预警"}
    if status == "at_risk" or confidence < 60:
        reason = "达成率距目标有差距" if status == "at_risk" else f"尽调置信度仅 {confidence}%"
        return {"level": 2, "label": "🔶 需要关注", "reason": reason}
    if status == "exceeded" and confidence >= 70:
        return {"level": 1, "label": "🌟 亮眼标杆", "reason": f"达成 {rate}% 且尽调可信"}
    return {"level": 0, "label": "✓ 正常推进", "reason": "按计划推进"}


def build_suggested_comment(report: Dict[str, Any]) -> str:
    """按风险级与关键指标生成批语草稿（60-100 字，可直接下发）"""
    risk = assess_review_risk(report)
    audit = report.get("supervision_audit") or {}
    confidence = audit.get("confidence_score", 70) or 70
    rate = report.get("completion_rate", 0) or 0
    actual_w = (report.get("actual_amount", 0) or 0) / 10000
    visits = report.get("visit_count", 0) or 0
    leads = report.get("new_leads", 0) or 0
    name = report.get("salesperson", "")
    blockers = _summarize(report.get("blockers", ""), 50)
    highlight = _summarize(report.get("highlight_summary", ""), 40)

    level = risk["level"]
    if level == 4:
        return (
            f"{name}本周触发{risk['reason'].replace('尽调徽章：', '')}，卡点：{blockers}。"
            "建议今日内亲自介入协调资源，优先消化尽调档案中的卡单死穴，并参考靶向派工锦囊制定破局动作。"
        )
    if level == 3 and "断崖" in risk["label"]:
        return (
            f"达成率 {rate}% 表面尚可，但过程指标预警（拜访 {visits} 家 / 新增线索 {leads} 条），存在断崖式下行风险。"
            "下周必须补足商机蓄水，建议安排主管陪访或线索支援，严防业绩跳水。"
        )
    if level == 3:
        return (
            f"{name}本周遇阻（{blockers}），建议 48 小时内一对一沟通，明确卡点责任人与解卡时间表，"
            "必要时协调法务/售前资源介入。"
        )
    if level == 2:
        return (
            f"本周达成率 {rate}%，距目标仍有差距（尽调置信度 {confidence}%）。"
            "建议下周初一起复盘商机漏斗，聚焦 2-3 个高意向客户重点突破，如需资源支持请及时提出。"
        )
    if level == 1:
        return (
            f"本周达成 {rate}%、签约 {actual_w:.1f} 万，尽调置信度 {confidence}%，表现优秀。"
            f"建议在组会上分享「{highlight}」的打法经验，并考虑给予资源倾斜冲刺更高目标。"
        )
    if report.get("status") == "growing":
        return (
            f"新人成长期表现稳健，拜访密度良好（{visits} 家次）。"
            "建议安排导师带教，聚焦 2-3 个高意向客户重点突破，循序渐进建立赢单信心。"
        )
    return (
        f"本周按计划推进（达成 {rate}%，回款情况正常）。继续保持拜访节奏，下周重点关注回款进度与在途订单签约。"
    )
