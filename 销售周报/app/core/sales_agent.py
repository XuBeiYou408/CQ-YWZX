"""
SalesAgent 战区总参谋长智能体 (SalesSupervisionAgent)
实现完整的 ReAct 状态机循环（感知 Perceive → 规划 Plan → 行动 Act → 反思定案 Reflect）
具备商机虚词剥离、业绩断崖预测、卡单死穴溯源与主管破局锦囊定制能力
"""
import copy
from datetime import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.core.agent_tools import (
    deal_substance_evaluator,
    pipeline_cliff_predictor,
    blocker_root_cause_tracer,
    tactical_dispatch_generator,
)
from app.core.llm_client import generate_chat

logger = logging.getLogger(__name__)


class SalesSupervisionAgent:
    """
    战区总参谋长与业绩真伪尽调智能体
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = cfg or {}

    async def run_deep_audit(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """
        运行 ReAct 督导与取证循环，产出带完整调查思维链的结构化评定档案
        """
        rep_name = report.get("salesperson", "销售代表")
        dept = report.get("department", "销售部")
        actual = report.get("actual_amount", 0.0)
        target = report.get("target_amount", 0.0)
        rate = report.get("completion_rate", 0.0)
        visits = report.get("visit_count", 0)
        leads = report.get("new_leads", 0)
        highlight = report.get("highlight_summary", "")
        blockers = report.get("blockers", "")
        next_plan = report.get("next_week_plan", "")
        raw_text = report.get("raw_content", "") or f"{highlight} {blockers} {next_plan}"

        investigation_trace: List[str] = []
        verified_highlights: List[str] = []
        risk_warnings: List[str] = []

        # =====================================================================
        # 阶段 1: 感知 (Perceive)
        # =====================================================================
        investigation_trace.append(
            f"【阶段 1: 感知 (Perceive)】抓取销售「{rep_name}（{dept}）」周报全景数据：签约 {actual/10000:.1f}万 / 目标 {target/10000:.1f}万 (达成率 {rate}%)，"
            f"客拜 {visits} 家，线索 {leads} 条。识别到核心战报亮点与潜在卡点求助信号，初始化督导审计任务..."
        )

        # =====================================================================
        # 阶段 2: 规划 (Plan)
        # =====================================================================
        plan_steps = [
            "1. 启动 deal_substance_evaluator 过滤口头承诺与模糊话术，核验真实成单证据链",
            "2. 启动 pipeline_cliff_predictor 交叉比对拜访与漏斗，推演未来 2~4 周断崖风险",
            "3. 启动 blocker_root_cause_tracer 穿透卡单本质（换届/竞品/合同/商务技能）",
            "4. 启动 tactical_dispatch_generator 输出主管破局攻坚锦囊与派工动作",
        ]
        investigation_trace.append(f"【阶段 2: 规划 (Plan)】制定四维督导尽调路径：\n  - " + "\n  - ".join(plan_steps))

        # =====================================================================
        # 阶段 3: 行动 (Act) - 调用 4 大工具链交叉取证
        # =====================================================================
        investigation_trace.append("【阶段 3: 行动 (Act)】依序调用战区工具箱开展多维交叉取证...")

        # 工具 1：商机脱水
        t1_substance = deal_substance_evaluator(raw_text, highlight)
        if t1_substance["buzzword_flags"]:
            for b in t1_substance["buzzword_flags"]:
                risk_warnings.append(f"⚠️ 商机水分警示：{b}")
                investigation_trace.append(f"  ⚡ 工具反馈 [商机虚词测谎]: 捕获模糊表述 -> {b}")
        else:
            investigation_trace.append(f"  ✓ 工具反馈 [商机虚词测谎]: 未见明显拖延推诿套话，成单事实描述紧凑")

        if t1_substance["substance_signals"]:
            for s in t1_substance["substance_signals"]:
                verified_highlights.append(f"✓ 凭证验真：{s}")
                investigation_trace.append(f"  ✓ 工具反馈 [凭证核实]: {s}")

        # 工具 2：断崖预测
        t2_cliff = pipeline_cliff_predictor(report)
        if t2_cliff["cliff_flags"]:
            for cf in t2_cliff["cliff_flags"]:
                risk_warnings.append(f"🚨 漏斗断崖预警：{cf}")
                investigation_trace.append(f"  ⚡ 工具反馈 [漏斗断崖预测]: {cf}")
        else:
            investigation_trace.append(f"  ✓ 工具反馈 [漏斗断崖预测]: 商机蓄水池充沛，近期无断崖风险")

        for hs in t2_cliff["health_signals"]:
            verified_highlights.append(f"✓ 蓄水健康：{hs}")
            investigation_trace.append(f"  ✓ 工具反馈 [漏斗蓄水]: {hs}")

        # 工具 3：卡单溯源
        t3_blocker = blocker_root_cause_tracer(blockers, report)
        if t3_blocker["has_blocker"]:
            for dn in t3_blocker["diagnostic_notes"]:
                risk_warnings.append(f"⚠️ 卡单定性：{t3_blocker['primary_cause']} - {dn}")
                investigation_trace.append(f"  ⚡ 工具反馈 [卡单死穴穿透]: 定性为「{t3_blocker['primary_cause']}」，严重程度：{t3_blocker['severity_label']}")
        else:
            investigation_trace.append("  ✓ 工具反馈 [卡单死穴穿透]: 本周无阻碍卡点，项目运行平稳")

        # 工具 4：主管派工锦囊
        t4_dispatch = tactical_dispatch_generator(report, t3_blocker)
        for act in t4_dispatch["dispatch_actions"]:
            investigation_trace.append(f"  🎯 工具反馈 [主管靶向派工]: {act}")

        # =====================================================================
        # 阶段 4: 反思定案 (Reflect)
        # =====================================================================
        investigation_trace.append("【阶段 4: 反思定案 (Reflect)】综合交叉取证数据，校准业绩置信度，输出督导结论...")

        # 确定性置信度综合推算 (0 - 100)
        calc_confidence = int(t1_substance["substance_score"] * 0.5 + (100 - t2_cliff["cliff_risk_score"]) * 0.35 + (rate / 100 * 15))
        if t3_blocker.get("severity") == "critical":
            calc_confidence = min(calc_confidence, 58)
        elif t3_blocker.get("severity") == "high":
            calc_confidence = min(calc_confidence, 72)
        confidence_score = max(35, min(98, calc_confidence))

        # 徽章裁决
        if t3_blocker.get("severity") == "critical" or "换届" in blockers:
            badge = "🚨 致命卡单"
            badge_class = "bg-rose-100 text-rose-800 border-rose-300"
        elif t2_cliff.get("cliff_level") == "high":
            badge = "⚠️ 断崖预警"
            badge_class = "bg-amber-100 text-amber-800 border-amber-300"
        elif t1_substance.get("level") == "low":
            badge = "🔍 商机存疑"
            badge_class = "bg-purple-100 text-purple-800 border-purple-300"
        elif rate >= 110 and t1_substance.get("level") == "high":
            badge = "✓ 战法验真"
            badge_class = "bg-emerald-100 text-emerald-800 border-emerald-300"
        elif report.get("status") == "growing":
            badge = "🌱 新人破局"
            badge_class = "bg-teal-100 text-teal-800 border-teal-300"
        else:
            badge = "✓ 稳步推进"
            badge_class = "bg-blue-100 text-blue-800 border-blue-300"

        # 兜底裁决结论
        summary_verdict = (
            f"销售「{rep_name}」当期达成率 {rate}%，真实业绩置信度测算为 {confidence_score}%。"
            f"商机脱水评级为【{t1_substance['level_label']}】，断崖风险评级为【{t2_cliff['cliff_label']}】。"
            f"{'存在重大卡单风险，需主管紧急介入。' if t3_blocker['requires_executive'] else '整体节奏受控，重点关注后续商机转化。'}"
        )

        # 尝试调用大模型润色提升商业洞察（支持离线优雅降级）
        try:
            if self.cfg:
                ai_prompt = f"""作为资深集团销售VP与战区参谋长，请基于以下工具链调查事实，对销售「{rep_name}」的周报进行一句话终审裁决（不超过80字）：
1. 达成数据：目标 {target/10000:.1f}万，签约 {actual/10000:.1f}万，达成率 {rate}%，客拜 {visits}家，线索 {leads}条
2. 商机脱水：得分 {t1_substance['substance_score']}，{t1_substance['level_label']}，捕获虚词：{t1_substance['buzzword_flags']}
3. 漏斗断崖：风险分 {t2_cliff['cliff_risk_score']}，{t2_cliff['cliff_label']}
4. 卡单死穴：{t3_blocker['primary_cause']} ({t3_blocker['severity_label']})
请输出严格格式：一句话犀利评述业务本质与下周破局关键。"""
                ai_verdict = await generate_chat(ai_prompt, "你是一位极度犀利、洞察敏锐的 B2B 销售 VP 战区参谋长。", self.cfg)
                if ai_verdict and len(ai_verdict.strip()) > 10:
                    summary_verdict = ai_verdict.strip()
                    investigation_trace.append(f"  💡 参谋长终审点评: {summary_verdict}")
        except Exception as e:
            logger.warning("SalesSupervisionAgent LLM verdict call failed: %s, using deterministic verdict", e)

        return {
            "confidence_score": confidence_score,
            "audit_badge": badge,
            "audit_badge_class": badge_class,
            "summary_verdict": summary_verdict,
            "verified_highlights": verified_highlights[:4],
            "risk_warnings": risk_warnings[:4],
            "tactical_tips": t4_dispatch["tactical_tips"],
            "dispatch_actions": t4_dispatch["dispatch_actions"],
            "investigation_trace": investigation_trace,
            "tools_data": {
                "substance": t1_substance,
                "cliff": t2_cliff,
                "blocker": t3_blocker,
                "dispatch": t4_dispatch,
            },
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
