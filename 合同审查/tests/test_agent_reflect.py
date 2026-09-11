"""
test_agent_reflect.py - Agent 反思层单元测试（FakeLLM，零真实模型依赖）
覆盖：
  1. verify_citations 幻觉核验：库内条文命中 / 库外条文标「未核实」/
     库内案号命中 / 库外案号标「未核实」/ all_verified 聚合判定
  2. _global_reflect 反思解析：合法 JSON 结构化 + 无效 clause_id 过滤 +
     垃圾输出兜底 {}
  3. _cross_validate 规则交叉验证：Agent 漏检条款自动补卡 / 已覆盖不重复
运行：python tests/test_agent_reflect.py
"""
import asyncio
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contract.statutes import verify_citations
from contract.agent import ContractReviewAgent
from contract.clause_splitter import _extract_signals, _candidate_labels


class FakeLLM:
    """固定回复的假 LLM（匹配 LLMClient.complete 签名）"""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    async def complete(self, messages, temperature=0.15, max_tokens=2400, want_json=False):
        self.calls += 1
        return self.reply


def _mk_clause(cid: str, heading: str, text: str) -> dict:
    sig = _extract_signals(heading, text)
    return {
        "clause_id": cid, "index": int(cid[1:]), "heading": heading, "text": text,
        "char_range": [0, len(text)], "signals": sig,
        "candidate_labels": _candidate_labels(heading, text, sig),
    }


# ------------------------------------------------------------------
# 1. verify_citations 幻觉核验
# ------------------------------------------------------------------
def test_verify_citations_hit():
    """库内条文（中文数字自动归一化 585）+ 库内案号 → 双命中"""
    text = (
        "依据《中华人民共和国民法典》第五百八十五条第二款，违约金过高应予调减；"
        "参见最高人民法院 (2020)最高法民终115号 与 (2022)最高法民终184号 裁判要旨。"
    )
    r = verify_citations(text)
    assert "585" in r["articles_verified"], r
    assert r["articles_unverified"] == [], r
    assert any("115" in c for c in r["cases_verified"]), r
    assert any("184" in c for c in r["cases_verified"]), r
    assert r["cases_unverified"] == [], r
    assert r["all_verified"] is True
    print("  [1] verify_citations 库内条文+案号双命中（中文数字归一化） ... OK")


def test_verify_citations_miss():
    """库外条文（第999条不在库）+ 库外案号 → 全部标「未核实」，all_verified=False"""
    text = (
        "根据《民法典》第九百九十九条之规定…；参见 (2022)最高法民终999号。"
    )
    r = verify_citations(text)
    assert "999" in r["articles_unverified"], r
    assert r["articles_verified"] == [], r
    assert any("999" in c for c in r["cases_unverified"]), r
    assert r["cases_verified"] == [], r
    assert r["all_verified"] is False
    print("  [2] verify_citations 库外引用标「未核实」 ... OK")


def test_verify_citations_mixed():
    """混合：库内+库外条文同现 → verified/unverified 各归其位"""
    text = "依据《民法典》第五百八十五条与第一千零三百六十八条处理。"
    r = verify_citations(text)
    assert "585" in r["articles_verified"], r
    assert "1368" in r["articles_unverified"], r  # 一千零三百六十八 = 1368
    assert r["all_verified"] is False
    print("  [3] verify_citations 混合引用分流 ... OK")


# ------------------------------------------------------------------
# 2. _global_reflect 反思解析
# ------------------------------------------------------------------
def _fake_plan():
    return {
        "contract_type": "软件开发合同",
        "overall_strategy": "",
        "clauses": [
            {"clause_id": "C01", "risk_score": 9, "action": "deep_dive", "why": "违约金", "tools": []},
            {"clause_id": "C02", "risk_score": 4, "action": "quick_scan", "why": "可疑信号", "tools": []},
            {"clause_id": "C03", "risk_score": 1, "action": "skip", "why": "模板条款", "tools": []},
        ],
        "summary": {"deep": 1, "quick": 1, "skip": 1, "budget_trimmed": []},
    }


def test_global_reflect_valid():
    """合法反思 JSON：结构化返回 + 无效 clause_id（C99）被过滤"""
    reply = (
        '```json\n{"missed_clause_ids": ["C01", "C99"], "final_rating": "🟡 中危可控", '
        '"confidence": 0.72, "overall_comment": "覆盖充分，担保条款可再确认", '
        '"levers": ["建议补充履约担保"]}\n```'
    )
    agent = ContractReviewAgent(FakeLLM(reply), time_budget_s=60)
    clauses = [_mk_clause(f"C0{i}", f"第{i}条", f"第{i}条内容。") for i in (1, 2, 3)]
    r = asyncio.run(agent._global_reflect(clauses, _fake_plan(), [], []))

    assert r["missed_clause_ids"] == ["C01"], r  # C99 不在条款清单，必须滤除
    assert r["final_rating"] == "🟡 中危可控"
    assert abs(r["confidence"] - 0.72) < 1e-6
    assert "覆盖充分" in r["overall_comment"]
    assert r["levers"] == ["建议补充履约担保"]
    assert agent._calls == 1
    print("  [4] _global_reflect 合法 JSON 结构化 + 无效 ID 过滤 ... OK")


def test_global_reflect_garbage():
    """反思输出为垃圾文本 → 兜底返回空 dict（不抛异常、不阻塞主流程）"""
    agent = ContractReviewAgent(FakeLLM("我觉得没什么问题，不需要 JSON。"), time_budget_s=60)
    clauses = [_mk_clause("C01", "第一条", "内容。")]
    r = asyncio.run(agent._global_reflect(clauses, _fake_plan(), [], []))
    assert r == {}, r
    print("  [5] _global_reflect 垃圾输出兜底 {} ... OK")


# ------------------------------------------------------------------
# 3. _cross_validate 规则交叉验证
# ------------------------------------------------------------------
HIGH_TEXT = "乙方迟延交货的，每日按合同总价5%向甲方支付违约金，并另行支付合同总价款100%的惩罚性赔偿金。"
HIGH_CLAUSE = _mk_clause("C01", "第一条 违约责任", HIGH_TEXT)


def test_cross_validate_fills_miss():
    """Agent 未产出 C01 风险卡但规则命中 → 自动补卡（source=cross_validation）"""
    agent = ContractReviewAgent(FakeLLM(""), time_budget_s=60)
    cross_cards, cross_hits = agent._cross_validate([HIGH_CLAUSE], [])
    assert len(cross_cards) == 1 and cross_cards[0]["clause_id"] == "C01"
    assert cross_cards[0]["source"] == "cross_validation"
    assert cross_cards[0]["severity"] == "high"
    assert "【条款原文引述】" in cross_cards[0]["card"]  # 卡片结构完整可渲染
    assert len(cross_hits) == 1
    assert cross_hits[0]["rule_title"]  # 命中规则有标题
    print("  [6] 交叉验证漏检补卡（cross_validation） ... OK")


def test_cross_validate_no_duplicate():
    """Agent 已产出该条款风险卡 → 不重复补卡"""
    agent = ContractReviewAgent(FakeLLM(""), time_budget_s=60)
    covered = [{"clause_id": "C01", "card": "Agent 自己的卡", "severity": "high"}]
    cross_cards, cross_hits = agent._cross_validate([HIGH_CLAUSE], covered)
    assert cross_cards == [] and cross_hits == []
    print("  [7] 交叉验证已覆盖条款不重复补卡 ... OK")


if __name__ == "__main__":
    print("=== test_agent_reflect.py 反思层单测 ===")
    test_verify_citations_hit()
    test_verify_citations_miss()
    test_verify_citations_mixed()
    test_global_reflect_valid()
    test_global_reflect_garbage()
    test_cross_validate_fills_miss()
    test_cross_validate_no_duplicate()
    print("=== 反思层 7 项测试全部通过 ===")
