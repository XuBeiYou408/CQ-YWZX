"""
SalesAgent 双层漏斗初筛引擎 (Screening Engine)
结合 L1 极速合规与数据守门员 (0 Token 毫秒硬核规则) 与 L2 战区总参谋长 ReAct 智能体尽调
"""
import copy
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from app.core.sales_agent import SalesSupervisionAgent

logger = logging.getLogger(__name__)


def check_hard_compliance_gates(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    L1 阶段：极速合规守门员 (0 Token 毫秒硬校验)
    核查必要字段完整性、财务数字逻辑冲突与反常零填报。
    """
    flags: List[str] = []
    is_critical = False
    
    rep_name = (report.get("salesperson") or "").strip()
    if not rep_name or rep_name == "未知":
        flags.append("缺少有效汇报人姓名")
        is_critical = True

    actual = report.get("actual_amount")
    if actual is None:
        flags.append("缺失核心指标「实际签约金额」")
        is_critical = True
    elif actual < 0:
        flags.append("签约金额异常：出现非法负数")
        is_critical = True

    collection = report.get("collection_amount")
    if collection is None:
        flags.append("缺失核心指标「实际回款金额」")
    elif collection < 0:
        flags.append("回款金额异常：出现非法负数")
        is_critical = True

    visits = report.get("visit_count", 0)
    leads = report.get("new_leads", 0)
    if visits == 0 and leads == 0 and (actual or 0) == 0:
        flags.append("过程与结果指标全面归零，疑似未实质填报")

    passed = not is_critical
    return {
        "passed": passed,
        "is_critical": is_critical,
        "flags": flags,
        "compliance_label": "合规校验通过" if passed else "合规硬性拦截",
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


async def run_report_screening_pipeline(
    report: Dict[str, Any],
    cfg: Optional[Dict[str, Any]] = None,
    skip_l2: bool = False
) -> Dict[str, Any]:
    """
    运行完整的双层漏斗初筛流水线：
    1. L1 守门员硬性校验
    2. L2 战区参谋长 ReAct 智能体多维深度尽调取证
    """
    # 1. 运行 L1 极速守门员
    l1_result = check_hard_compliance_gates(report)
    report["hard_gate"] = l1_result

    # 若未致命拦截且未跳过 L2，启动 L2 智能体深度穿透
    if l1_result["passed"] and not skip_l2:
        agent = SalesSupervisionAgent(cfg)
        audit_result = await agent.run_deep_audit(report)
        report["supervision_audit"] = audit_result
    elif not l1_result["passed"]:
        # 拦截记录
        report["supervision_audit"] = {
            "confidence_score": 20,
            "audit_badge": "⛔ 合规拦截",
            "audit_badge_class": "bg-red-100 text-red-800 border-red-300",
            "summary_verdict": f"该周报未通过 L1 硬性合规门槛：{'; '.join(l1_result['flags'])}，已被系统退回。",
            "verified_highlights": [],
            "risk_warnings": [f"硬性违规：{f}" for f in l1_result["flags"]],
            "tactical_tips": ["请通知该销售代表重新补正周报关键财务指标后重新提报。"],
            "dispatch_actions": ["【主管打回重填】驳回该周报，要求于周六中午 12:00 前完成数据修正。"],
            "investigation_trace": [
                "【阶段 1: 守门员拦截】检测到周报存在硬性数据缺失或逻辑冲突，触发 L1 熔断机制，终止向大模型分流。"
            ],
            "tools_data": {},
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    return report
