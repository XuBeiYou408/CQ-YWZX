"""
test_agent_loop_guard.py - Agent 主循环预算守卫集成测试（FakeLLM，零真实模型依赖）
验证 ReAct 循环的三道护栏，确保「模型再失控也不会拖垮系统」：
  1. 无限工具调用 → 工具轮次封顶（max_tool_rounds）+ 强制收敛追问，仍产出报告
  2. 无限 self-check 重试 → 重试次数封顶（max_retry ≤ 2），仍产出报告
  3. 全局时间预算触顶 → 立即停止深查、强制收敛进入反思/组装，仍产出报告
运行：python tests/test_agent_loop_guard.py
"""
import asyncio
import os
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contract.agent import ContractReviewAgent
from config import config

MAX_TOOL_ROUNDS = config.AGENT_MAX_TOOL_ROUNDS_PER_CLAUSE
MAX_RETRY = config.AGENT_MAX_RETRY_PER_CLAUSE

# ------------------------------------------------------------------
# 合同 fixture：3 条款（C01 规则命中 / C02 可疑 / C03 模板）
# ------------------------------------------------------------------
SAMPLE_CONTRACT = """软件开发合同

第一条 违约责任
乙方迟延交货的，每日按合同总价5%向甲方支付违约金，并另行支付合同总价款100%的惩罚性赔偿金。

第二条 合作机制
甲方有权无条件随时终止本协议，且无需说明理由。

第三条 其他约定
本合同自双方签字盖章之日起生效，一式两份，具有同等法律效力。
"""

PLAN_JSON = (
    '{"contract_type": "软件开发合同", "overall_strategy": "重点审查违约与合作条款", '
    '"clauses": ['
    '{"clause_id": "C01", "risk_score": 9, "action": "deep_dive", "why": "违约金畸高"}, '
    '{"clause_id": "C02", "risk_score": 8, "action": "deep_dive", "why": "单方解除权"}, '
    '{"clause_id": "C03", "risk_score": 1, "action": "skip", "why": "模板条款"}]}'
)

REFLECT_JSON = (
    '{"missed_clause_ids": [], "final_rating": "🟡 中危可控", '
    '"confidence": 0.75, "overall_comment": "复核无漏检"}'
)

TOOL_CALL = '<tool_call>{"name": "rule_scan", "args": {"text": "违约金 5% 惩罚性赔偿"}}</tool_call>'

FINAL_CARD = (
    "#### 🔴 [高危风险] 条款 — 违约金畸高\n"
    "- **【条款原文引述】**：「每日按合同总价5%向甲方支付违约金，并另行支付100%惩罚性赔偿金。」\n"
    "- **【法理风险解构】**：日5%折合年化1825%，严重超出司法保护上限，构成显失公平。\n"
    "- **【合规修改建议初稿】**：调整为日万分之五且以实际损失的30%为限。\n"
    '<selfcheck>{"need_more": false, "confidence": 0.9}</selfcheck>'
)

LOW_CONF_CARD = (
    TOOL_CALL + "\n"
    "#### 🔴 [高危风险] 条款 — 违约金畸高\n"
    "- **【条款原文引述】**：「每日按合同总价5%向甲方支付违约金。」\n"
    "- **【法理风险解构】**：畸高但证据仍不足，需补充同类判例。\n"
    "- **【合规修改建议初稿】**：调整为日万分之五。\n"
    '<selfcheck>{"need_more": true, "confidence": 0.3}</selfcheck>'
)


class FakeLLM:
    """按 System Prompt 特征路由的假 LLM（匹配 LLMClient.complete 签名）"""

    def __init__(self, deep_mode="tool_then_final", deep_sleep=0.0):
        self.deep_mode = deep_mode
        self.deep_sleep = deep_sleep
        self.counts = {"plan": 0, "deep": 0, "quick": 0, "reflect": 0}

    async def complete(self, messages, temperature=0.15, max_tokens=2400, want_json=False):
        sys_text = messages[0]["content"] if messages else ""
        # 注意顺序：全局反思/快筛的 Prompt 中也可能含 "deep_dive" 字样，必须先特判
        if "分诊规划" in sys_text:
            self.counts["plan"] += 1
            return PLAN_JSON
        if "全局反思" in sys_text:
            self.counts["reflect"] += 1
            return REFLECT_JSON
        if "快筛核验" in sys_text:
            self.counts["quick"] += 1
            return '{"upgrades": []}'
        if "deep_dive" in sys_text:
            self.counts["deep"] += 1
            if self.deep_sleep:
                time.sleep(self.deep_sleep)
            if self.deep_mode == "always_low_conf":
                return LOW_CONF_CARD
            # tool_then_final：前 max_tool_rounds 轮只给工具调用，
            # 第 max_tool_rounds+1 次（强制收敛追问）才给最终卡片
            if self.counts["deep"] % (MAX_TOOL_ROUNDS + 1) == 0:
                return FINAL_CARD
            return TOOL_CALL
        raise RuntimeError("FakeLLM 未知路由: " + sys_text[:60])


async def _collect(agent):
    frames = []
    async for frame in agent.run(SAMPLE_CONTRACT, "auto", "乙方", "对等平衡"):
        frames.append(frame)
    return frames


def _report_text(frames):
    for f in frames:
        if f["type"] == "agent_report":
            return f["data"]
    return ""


# ------------------------------------------------------------------
# 1. 无限工具调用 → 轮次封顶 + 强制收敛
# ------------------------------------------------------------------
def test_infinite_tool_calls_capped():
    llm = FakeLLM(deep_mode="tool_then_final")
    agent = ContractReviewAgent(llm, time_budget_s=120)
    frames = asyncio.run(_collect(agent))

    types = {f["type"] for f in frames}
    assert "agent_report" in types, types
    assert "perceive" in types and "plan" in types, types

    # 2 条深查条款 × (max_tool_rounds 轮 + 1 次强制收敛) = 精确上界
    expected = 2 * (MAX_TOOL_ROUNDS + 1)
    assert llm.counts["deep"] == expected, (
        f"深查调用必须精确封顶 {expected} 次，实际 {llm.counts['deep']}（防止模型无限取证）"
    )

    # 强制收敛后仍产出有效卡片
    risk_frames = [f for f in frames if f["type"] == "risk_card" and f["data"].get("card")]
    assert len(risk_frames) >= 2, "强制收敛后两条深查条款都应产出卡片"

    report = _report_text(frames)
    assert "违约金" in report and "### 📊" in report, "报告必须包含收敛后的卡片内容"
    print(f"  [1] 无限工具调用 → 轮次封顶（{llm.counts['deep']} 次 = 2×{MAX_TOOL_ROUNDS + 1}）"
          f" + 强制收敛出卡 ... OK")


# ------------------------------------------------------------------
# 2. 无限 self-check 重试 → max_retry 封顶
# ------------------------------------------------------------------
def test_infinite_selfcheck_retry_capped():
    llm = FakeLLM(deep_mode="always_low_conf")
    agent = ContractReviewAgent(llm, time_budget_s=120)
    frames = asyncio.run(_collect(agent))

    types = {f["type"] for f in frames}
    assert "agent_report" in types, types

    # 每条深查 = range(max_tool_rounds+1) 共 4 轮 + 1 强制收敛 + max_retry 次重取证
    expected = 2 * (MAX_TOOL_ROUNDS + 2 + MAX_RETRY)
    assert llm.counts["deep"] == expected, (
        f"self-check 重试必须封顶：期望 {expected}，实际 {llm.counts['deep']}"
    )

    # 重试轨迹应有记录
    retry_traces = [f for f in frames if f["type"] == "trace"
                    and f["data"].get("step") == "selfcheck_retry"]
    assert len(retry_traces) == 2 * MAX_RETRY, f"应有 {2 * MAX_RETRY} 条重试轨迹, got {len(retry_traces)}"

    report = _report_text(frames)
    assert "### 📊" in report
    print(f"  [2] 无限 self-check 重试 → {llm.counts['deep']} 次封顶"
          f"（轮次+收敛+{MAX_RETRY} 重试/条） ... OK")


# ------------------------------------------------------------------
# 3. 时间预算触顶 → 强制收敛仍出报告
# ------------------------------------------------------------------
def test_time_budget_forces_convergence():
    # 每次深查调用 90ms：C01 四轮 = 360ms > 300ms 预算，
    # 回到主循环检查点时预算必然已触顶 → 广播 fallback_notice 并强制收敛
    llm = FakeLLM(deep_mode="tool_then_final", deep_sleep=0.09)
    agent = ContractReviewAgent(llm, time_budget_s=0.3)  # 极小预算触发触顶
    frames = asyncio.run(_collect(agent))

    types = {f["type"] for f in frames}
    assert "agent_report" in types, "预算触顶也必须产出报告（下限不降低）"

    # 必须发出预算收敛通知
    budget_notices = [f for f in frames if f["type"] == "fallback_notice"
                      and (f.get("data") or {}).get("reason") == "time_budget"]
    assert budget_notices, "预算触顶必须广播 fallback_notice(time_budget)"

    # 深查被中断：C01 至多 5 次调用（4 轮+收敛），C02 不再执行
    assert 1 <= llm.counts["deep"] <= MAX_TOOL_ROUNDS + 1 + 1, llm.counts["deep"]
    # 深查被中断 → 快筛与全局反思不再消耗模型
    assert llm.counts["quick"] == 0
    assert llm.counts["reflect"] == 0

    report = _report_text(frames)
    assert report.strip(), "报告不能为空"
    assert "### 📊" in report, "报告保持旧格式兼容（annotator/前端 stats 依赖）"
    print(f"  [3] 时间预算触顶 → 深查 {llm.counts['deep']} 次即中断、"
          f"强制收敛仍出完整报告 ... OK")


if __name__ == "__main__":
    print("=== test_agent_loop_guard.py 预算守卫集成测试 ===")
    test_infinite_tool_calls_capped()
    test_infinite_selfcheck_retry_capped()
    test_time_budget_forces_convergence()
    print("=== 预算守卫 3 项测试全部通过 ===")
