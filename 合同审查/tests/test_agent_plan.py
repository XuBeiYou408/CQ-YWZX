"""
test_agent_plan.py - Agent 规划层单元测试（纯函数，零模型依赖）
覆盖：
  1. parse_plan 正常解析 + 未覆盖条款自动补 quick_scan
  2. 评分与动作矛盾时以评分为准（skip 声明但 score=9 → 不允许跳过）
  3. 动作非法时按评分阈值映射
  4. deep_dive 超预算硬裁剪（保留 top 分数，其余降级并标注）
  5. 全垃圾输入的兜底结构
  6. rule_fallback_plan 规则路由回退（规则命中→deep / 可疑→quick / 模板→skip）
运行：python tests/test_agent_plan.py
"""
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contract.planner import parse_plan, rule_fallback_plan, _score_to_action
from contract.clause_splitter import _extract_signals, _candidate_labels


def _mk_clause(cid: str, heading: str, text: str) -> dict:
    """构造与拆条器同构的条款结构（signals/candidate_labels 走真实函数）"""
    sig = _extract_signals(heading, text)
    return {
        "clause_id": cid,
        "index": int(cid[1:]),
        "heading": heading,
        "text": text,
        "char_range": [0, len(text)],
        "signals": sig,
        "candidate_labels": _candidate_labels(heading, text, sig),
    }


# 固定测试条款：
#  - HIGH：命中规则卡 R1 关键词「5%」（违约金畸高）
#  - SUSP：含「无条件」可疑信号但无规则卡关键词
#  - PLAIN：常规模板（heading 含「其他」且正文 < 400 字）
HIGH = _mk_clause("C01", "第一条 违约责任",
                  "乙方迟延交货的，每日按合同总价5%向甲方支付违约金，并另行支付合同总价款100%的惩罚性赔偿金。")
SUSP = _mk_clause("C02", "第二条 合作机制",
                  "甲方有权无条件随时终止本协议，且无需说明理由。")
PLAIN = _mk_clause("C03", "第三条 其他约定",
                   "本合同自双方签字盖章之日起生效，一式两份，具有同等法律效力。")

CLAUSES = [HIGH, SUSP, PLAIN]


def test_parse_plan_basic_and_fill():
    """正常解析 + 未覆盖条款自动补 quick_scan（宁可不跳过，不可漏）"""
    raw = {
        "contract_type": "软件开发合同",
        "overall_strategy": "重点审查违约与付款条款",
        "clauses": [
            {"clause_id": "C01", "risk_score": 9, "action": "deep_dive",
             "why": "违约金畸高", "tools": ["precedent_search"]},
        ],
    }
    plan = parse_plan(raw, CLAUSES, max_deep=5)
    ids = [e["clause_id"] for e in plan["clauses"]]
    assert ids == ["C01", "C02", "C03"], f"条款顺序应与输入一致: {ids}"

    e1 = plan["clauses"][0]
    assert e1["action"] == "deep_dive" and e1["risk_score"] == 9
    assert e1["why"] == "违约金畸高"
    assert e1["tools"] == ["precedent_search"]

    # 未覆盖的 C02/C03 一律补 quick_scan（防漏检）
    for e in plan["clauses"][1:]:
        assert e["action"] == "quick_scan", e
        assert e["risk_score"] == 4
        assert "分诊未覆盖" in e["why"]

    assert plan["summary"] == {"deep": 1, "quick": 2, "skip": 0, "budget_trimmed": []}
    assert plan["contract_type"] == "软件开发合同"
    print("  [1] parse_plan 正常解析 + 未覆盖补 quick_scan ... OK")


def test_score_overrides_action():
    """动作与评分严重矛盾时以评分为准（模型不能靠标 skip 绕过高分条款）"""
    raw = {"clauses": [
        {"clause_id": "C01", "risk_score": 9, "action": "skip", "why": "想跳过"},
        {"clause_id": "C02", "risk_score": 1, "action": "deep_dive", "why": "想深查"},
        {"clause_id": "C03", "risk_score": 5, "action": "flower", "why": "乱写动作"},
    ]}
    plan = parse_plan(raw, CLAUSES, max_deep=5)
    acts = {e["clause_id"]: e["action"] for e in plan["clauses"]}
    # score=9 标 skip → 至少 quick_scan，不允许 skip
    assert acts["C01"] in ("quick_scan", "deep_dive") and acts["C01"] != "skip", acts
    # score=1 标 deep_dive → 降为 quick_scan
    assert acts["C02"] == "quick_scan", acts
    # 动作非法 + score=5（3~5 区间）→ quick_scan
    assert acts["C03"] == "quick_scan", acts
    print("  [2] 评分矛盾裁决 + 非法动作映射 ... OK")


def test_score_to_action_thresholds():
    """_score_to_action 阈值映射：≥6 deep / ≤2 skip / 中间 quick / 全非法 quick"""
    assert _score_to_action(8, "unknown_action") == "deep_dive"
    assert _score_to_action(1, "unknown_action") == "skip"
    assert _score_to_action(4, None) == "quick_scan"
    assert _score_to_action("abc", None) == "quick_scan"  # 评分也非法 → 兜底快筛
    print("  [3] _score_to_action 阈值映射 ... OK")


def test_budget_trim():
    """deep_dive 超预算硬裁剪：保留评分 top-N，其余降级并标注 [预算裁剪]"""
    clauses = []
    for i in range(1, 9):
        clauses.append(_mk_clause(f"C{i:02d}", f"第{i}条 条款{i}", f"这是第{i}条的正常约定内容。"))
    raw = {"clauses": [
        {"clause_id": f"C{i:02d}", "risk_score": 11 - i, "action": "deep_dive", "why": f"条款{i}风险"}
        for i in range(1, 9)  # 8 条全 deep，评分 10..3
    ]}
    plan = parse_plan(raw, clauses, max_deep=3)
    deep = [e for e in plan["clauses"] if e["action"] == "deep_dive"]
    trimmed = [e for e in plan["clauses"] if "[预算裁剪]" in e["why"]]

    assert len(deep) == 3, f"深查必须裁到预算 3 条, got {len(deep)}"
    # 保留的必须是评分前 3（10/9/8 → C01/C02/C03）
    assert [e["clause_id"] for e in deep] == ["C01", "C02", "C03"], deep
    assert len(trimmed) == 5
    assert all(e["action"] == "quick_scan" for e in trimmed)
    assert plan["summary"]["budget_trimmed"] == ["C04", "C05", "C06", "C07", "C08"]
    print("  [4] 深查预算硬裁剪（8→3，标注与清单正确） ... OK")


def test_garbage_inputs():
    """全垃圾输入：仍返回结构完整的兜底计划（不抛异常）"""
    for raw in (None, "我不会输出JSON", 12345, {"clauses": [{"clause_id": "C99", "risk_score": 9}]}):
        plan = parse_plan(raw, CLAUSES, max_deep=5)
        assert len(plan["clauses"]) == 3
        assert all(e["action"] == "quick_scan" for e in plan["clauses"])
        assert plan["summary"]["deep"] == 0
    print("  [5] 垃圾输入兜底（无效 ID 过滤 + 全量补筛） ... OK")


def test_rule_fallback_plan():
    """分诊失败规则路由回退：规则命中→deep / 可疑信号→quick / 模板→skip"""
    plan = rule_fallback_plan(CLAUSES, max_deep=5)
    acts = {e["clause_id"]: (e["action"], e["risk_score"], e["why"]) for e in plan["clauses"]}

    # HIGH 命中 R1（关键词「5%」）→ deep_dive 9 分
    assert acts["C01"][0] == "deep_dive" and acts["C01"][1] == 9, acts["C01"]
    assert "规则引擎关键词命中" in acts["C01"][2]
    # SUSP 含「无条件」→ quick_scan 4 分
    assert acts["C02"][0] == "quick_scan" and acts["C02"][1] == 4, acts["C02"]
    # PLAIN 模板 → skip 1 分
    assert acts["C03"][0] == "skip" and acts["C03"][1] == 1, acts["C03"]
    assert "常规模板" in acts["C03"][2]
    print("  [6] rule_fallback_plan 规则路由回退（下限不降低） ... OK")


if __name__ == "__main__":
    print("=== test_agent_plan.py 规划层单测 ===")
    test_parse_plan_basic_and_fill()
    test_score_overrides_action()
    test_score_to_action_thresholds()
    test_budget_trim()
    test_garbage_inputs()
    test_rule_fallback_plan()
    print("=== 规划层 6 项测试全部通过 ===")
