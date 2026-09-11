"""
智审 (Doc-Agent) - Agent 规划层（分诊 Triage）
本次升级的灵魂：模型先看条款清单做分级规划（深查/快筛/跳过），
再对需深查的条款逐个调用工具取证。

职责边界：
  - make_plan_messages：组装分诊 Prompt（含预算硬约束）
  - parse_plan：宽松解析模型分诊 JSON（评分→动作映射容错、why 补全、预算封顶裁剪）
  - rule_fallback_plan：分诊失败时的规则路由回退计划（保证下限不降低）
"""

import re
from typing import Any, Dict, List

from contract.rule_cards import RULE_CARDS

VALID_ACTIONS = {"deep_dive", "quick_scan", "skip"}


def make_plan_messages(
    clauses_listing: str,
    keyword_type: str,
    client_role: str,
    review_stance: str,
    focus_dimensions: List[str] = None,
    max_deep: int = 5,
) -> List[Dict[str, str]]:
    """组装分诊规划的 messages（系统提示词内嵌预算硬约束）"""
    from contract.prompts import PLAN_SYSTEM_PROMPT, render_prompt

    focus_str = "、".join(focus_dimensions) if focus_dimensions else "无特别指定"
    system = render_prompt(PLAN_SYSTEM_PROMPT, max_deep=max_deep)
    user = (
        f"【关键词预判的合同类型】：{keyword_type}\n"
        f"【审查立场】：代表【{client_role}】（审查风格：{review_stance}）\n"
        f"【重点关注维度】：{focus_str}\n\n"
        f"【条款清单】（clause_id + 标题 + 线索 + 正文摘要）：\n{clauses_listing}\n\n"
        f"请输出分诊计划 JSON（deep_dive 总数 ≤ {max_deep} 条，每条必须附 why）。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _score_to_action(score: Any, action: Any) -> str:
    """动作容错：action 非法时按评分阈值映射；评分也非法时降级 quick_scan"""
    try:
        s = int(score)
    except (TypeError, ValueError):
        s = None

    if action in VALID_ACTIONS:
        # 动作合法但与评分严重矛盾时以评分为准（如 score=9 却标 skip）
        if s is not None:
            if s >= 6 and action == "skip":
                return "quick_scan"
            if s <= 2 and action == "deep_dive":
                return "quick_scan"
        return action
    if s is None:
        return "quick_scan"
    if s >= 6:
        return "deep_dive"
    if s <= 2:
        return "skip"
    return "quick_scan"


def parse_plan(raw: Any, clauses: List[Dict[str, Any]], max_deep: int = 5) -> Dict[str, Any]:
    """
    解析并归一化分诊计划：
    - 未覆盖的条款自动补 quick_scan（宁可不跳过，不可漏）
    - deep_dive 超预算时按评分裁剪（保留 top max_deep，其余降 quick_scan）
    - why 缺失时补「模型未提供理由」
    """
    clause_ids = {c["clause_id"] for c in clauses}
    entries: Dict[str, Dict[str, Any]] = {}
    contract_type = ""
    overall_strategy = ""

    if isinstance(raw, dict):
        contract_type = str(raw.get("contract_type") or "").strip()
        overall_strategy = str(raw.get("overall_strategy") or "").strip()
        raw_clauses = raw.get("clauses") or raw.get("triage_plan") or []
        if isinstance(raw_clauses, list):
            for item in raw_clauses:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("clause_id") or item.get("id") or "").strip()
                if cid not in clause_ids:
                    continue
                action = _score_to_action(item.get("risk_score"), item.get("action"))
                try:
                    score = max(0, min(10, int(item.get("risk_score"))))
                except (TypeError, ValueError):
                    score = 5 if action == "quick_scan" else (8 if action == "deep_dive" else 1)
                tools = [t for t in (item.get("tools") or []) if isinstance(t, str)][:3]
                why = str(item.get("why") or item.get("reason") or "").strip() or "模型未提供理由"
                entries[cid] = {
                    "clause_id": cid,
                    "risk_score": score,
                    "action": action,
                    "why": why[:200],
                    "tools": tools,
                }

    # 未覆盖条款统一补 quick_scan（含 why）
    for c in clauses:
        if c["clause_id"] not in entries:
            entries[c["clause_id"]] = {
                "clause_id": c["clause_id"],
                "risk_score": 4,
                "action": "quick_scan",
                "why": "分诊未覆盖，默认快筛以防漏检",
                "tools": [],
            }

    # 预算硬约束：deep_dive 裁剪
    deep_ids = [cid for cid, e in entries.items() if e["action"] == "deep_dive"]
    trimmed = []
    if len(deep_ids) > max_deep:
        deep_ids_sorted = sorted(
            deep_ids, key=lambda cid: entries[cid]["risk_score"], reverse=True
        )
        keep = set(deep_ids_sorted[:max_deep])
        for cid in deep_ids:
            if cid not in keep:
                entries[cid]["action"] = "quick_scan"
                entries[cid]["why"] = f"[预算裁剪] 原判深查，因深查预算 ≤{max_deep} 条降级快筛：" + entries[cid]["why"]
                trimmed.append(cid)

    summary = {
        "deep": sum(1 for e in entries.values() if e["action"] == "deep_dive"),
        "quick": sum(1 for e in entries.values() if e["action"] == "quick_scan"),
        "skip": sum(1 for e in entries.values() if e["action"] == "skip"),
        "budget_trimmed": trimmed,
    }
    return {
        "contract_type": contract_type,
        "overall_strategy": overall_strategy,
        "clauses": [entries[c["clause_id"]] for c in clauses],
        "summary": summary,
    }


def rule_fallback_plan(clauses: List[Dict[str, Any]], max_deep: int = 5) -> Dict[str, Any]:
    """
    分诊失败的规则路由回退：规则引擎关键词命中 → deep_dive；
    含可疑信号（金额/单方/无条件等）→ quick_scan；其余 skip。
    保证「模型失效时系统下限不降低」。
    """
    entries: List[Dict[str, Any]] = []
    for c in clauses:
        text = c["text"]
        sig = c.get("signals", {})

        rule_hits = 0
        for rule in RULE_CARDS:
            if any(k in text for k in rule["keywords"]):
                rule_hits += 1

        if rule_hits > 0:
            action, score = "deep_dive", 9
            why = f"规则引擎关键词命中 {rule_hits} 组高危模式（规则路由回退）"
        elif sig.get("suspicious") or sig.get("candidate_labels"):
            action, score = "quick_scan", 4
            why = "含可疑信号：" + ("、".join(sig.get("candidate_labels", [])) or "金额/单方类信号")
        elif sig.get("is_standard_boilerplate"):
            action, score = "skip", 1
            why = "常规模板条款（规则路由回退判定）"
        else:
            action, score = "quick_scan", 3
            why = "无明确信号，默认快筛（规则路由回退）"

        entries.append({
            "clause_id": c["clause_id"],
            "risk_score": score,
            "action": action,
            "why": why,
            "tools": ["rule_scan"] if action == "deep_dive" else [],
        })

    return parse_plan({"clauses": entries}, clauses, max_deep=max_deep)
