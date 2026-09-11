"""
智审 (Doc-Agent) - MCP 轻量工具层（Tool 轨）
================================================
设计原则（见 合同改造计划书/合同审查双轨改造方案-轻量Tool轨.md）：
1. import 白名单：仅只读核心层 statutes / rule_cards / precedents / parser(+data CSV)
   —— 绝不 import engine / agent / planner / tools，与 Agent 轨零共享可变状态
2. 全部同步函数、无 LLM 调用、无状态，每次调用独立，秒级返回
3. 返回统一为 Markdown 结构化文本，WorkBuddy 宿主模型可直接消费
4. 所有输入内置截断保护，防超长文本拖垮响应
"""
import csv
import os
from typing import List, Dict, Any

from contract.rule_cards import scan_rules, render_rule_card
from contract.statutes import search_statutes, format_statute_for_prompt
from contract.precedents import search_by_risk_point
from contract.parser import detect_contract_type

# clause_standards.csv 与本文件同属 contract 包，路径基于包目录解析
_STANDARDS_CSV = os.path.join(os.path.dirname(__file__), "data", "clause_standards.csv")


def _clip(text: str, limit: int) -> str:
    return (text or "").strip()[:limit]


# ------------------------------------------------------------------
# 1. 条款风险扫描（纯规则引擎，无 LLM）
# ------------------------------------------------------------------
def scan_clause_risk(clause_text: str) -> str:
    """对单条条款（或合同片段）执行 5 组高危霸王条款规则穿透。"""
    clause_text = _clip(clause_text, 2000)
    if not clause_text:
        return "⚠️ 未提供条款文本，无法扫描。"

    hits = scan_rules(clause_text)
    if not hits:
        return (
            "✅ **规则引擎扫描结果：未命中已知高危模式**\n\n"
            "当前 5 组高危穿透规则（畸高违约金 / 单方免责 / 随时解约零补偿 / "
            "侵吞既有知识产权 / 超长验收期+苛刻付款）均未命中该条款。\n"
            "提示：规则引擎只覆盖典型高危套路，如需全维度深度审查（16 类专项门禁 + "
            "判例比对），请使用 review_contract 进行完整审查。"
        )

    cards = []
    for h in hits:
        cards.append(
            f"#### 🔴 [{h['severity']}] {h['title']}\n"
            + render_rule_card(h, f"“{clause_text}”")
        )
    return (
        f"🚨 **规则引擎命中 {len(hits)} 项高危风险**\n\n" + "\n\n".join(cards)
    )


# ------------------------------------------------------------------
# 2. 法条检索（纯关键词检索，无 LLM）
# ------------------------------------------------------------------
def lookup_statute(keyword: str, top_k: int = 3) -> str:
    """按关键词检索内置法条库（民法典合同编 + 最高法合同编通则解释等）。"""
    keyword = _clip(keyword, 200)
    if not keyword:
        return "⚠️ 未提供检索关键词。"
    top_k = max(1, min(int(top_k or 3), 5))

    results = search_statutes(keyword, top_k=top_k)
    if not results:
        return (
            f"❌ 法条库中未检索到与「{keyword}」相关的条文。\n"
            "内置法条库聚焦合同编高频争议（违约金/解除/格式条款/担保等），"
            "可尝试更换关键词（如“违约金过高”“格式条款无效”“法定解除”）。"
        )

    blocks = [f"**{i+1}. {format_statute_for_prompt(st)}**" for i, st in enumerate(results)]
    return f"📚 **法条检索结果（关键词：{keyword}，命中 {len(results)} 条）**\n\n" + "\n\n".join(blocks)


# ------------------------------------------------------------------
# 3. 判例检索（纯关键词匹配，无 LLM）
# ------------------------------------------------------------------
def search_precedent(query: str, top_k: int = 3) -> str:
    """按风险点描述检索最高法裁判指引判例库。"""
    query = _clip(query, 200)
    if not query:
        return "⚠️ 未提供风险点描述。"
    top_k = max(1, min(int(top_k or 3), 5))

    results = search_by_risk_point(query, top_k=top_k)
    if not results:
        return (
            f"❌ 判例库中未检索到与「{query}」相关的案例。\n"
            "可尝试更换描述角度（如“违约金酌减”“对赌回购”“格式条款”“验收付款”）。"
        )

    blocks = []
    for i, p in enumerate(results, 1):
        title = p.get("title") or p.get("case_name") or "未命名案例"
        case_no = p.get("case_no") or p.get("case_number") or ""
        gist = p.get("gist") or p.get("holding") or p.get("summary") or ""
        advice = p.get("advice") or p.get("practice_advice") or ""
        seg = f"**{i}. {title}**"
        if case_no:
            seg += f"\n- 案号：{case_no}"
        if gist:
            seg += f"\n- 裁判要旨：{gist}"
        if advice:
            seg += f"\n- 实务建议：{advice}"
        blocks.append(seg)
    return f"🏛️ **判例检索结果（命中 {len(results)} 例）**\n\n" + "\n\n".join(blocks)


# ------------------------------------------------------------------
# 4. 合同类型识别（纯关键词+规则匹配，无 LLM）
# ------------------------------------------------------------------
def identify_contract_type(contract_text: str) -> str:
    """识别合同文本所属类型（买卖/租赁/劳动/技术开发/股权转让等）。"""
    contract_text = _clip(contract_text, 8000)
    if not contract_text:
        return "⚠️ 未提供合同文本。"
    detected = detect_contract_type(contract_text)
    return (
        f"📄 **合同类型识别结果**：{detected}\n\n"
        "提示：识别结果将作为完整审查（review_contract）与标准条款推荐"
        "（get_clause_rewrite）的类型依据。"
    )


# ------------------------------------------------------------------
# 5. 条款改写建议（规则引擎 + clause_standards.csv 标准模板，无 LLM）
# ------------------------------------------------------------------
def _load_standards() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    try:
        with open(_STANDARDS_CSV, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        pass
    return rows


def get_clause_rewrite(clause_text: str, contract_type: str = "") -> str:
    """
    对条款给出合规改写建议：规则引擎修改建议（若命中）+ 标准条款示范模板 + 要素清单。
    contract_type 可选，传入可精确匹配该类型的标准模板（可先调 identify_contract_type）。
    """
    clause_text = _clip(clause_text, 2000)
    if not clause_text:
        return "⚠️ 未提供条款文本。"

    parts: List[str] = []

    # (a) 规则引擎命中的高危修改建议
    hits = scan_rules(clause_text)
    if hits:
        parts.append("🚨 **规则引擎判定该条款存在高危风险，给出如下合规改写：**")
        for h in hits:
            parts.append(
                f"**[{h['rule_id']}] {h['title']}**\n"
                f"- 修改建议：{h['suggestion']}"
            )
    else:
        parts.append("✅ 规则引擎未命中高危模式，以下提供标准条款示范模板供对照完善。")

    # (b) clause_standards.csv 标准模板匹配：按 contract_type 精确 → 通用回退
    rows = _load_standards()
    if rows:
        ct = (contract_type or "").strip()
        scored = []
        for r in rows:
            row_type = (r.get("contract_type") or "").strip()
            type_bonus = 1 if (not ct or row_type == ct or row_type == "通用") else 0
            # 条款类型关键词（如“标的”“价款”“违约”）在条款文本中出现则加分
            clause_kw = (r.get("clause_type") or "").replace("条款", "").replace("与支付", "")
            kw_bonus = 2 if (clause_kw and clause_kw in clause_text) else 0
            if kw_bonus > 0 or type_bonus > 0:
                scored.append((kw_bonus + type_bonus, r))
        scored.sort(key=lambda x: x[0], reverse=True)

        if scored:
            r = scored[0][1]
            parts.append(
                "📝 **标准条款示范模板（来源：clause_standards.csv）**\n"
                f"- 条款类别：{r.get('clause_type', '')}（适用：{r.get('contract_type', '')}）\n"
                f"- 模板：{r.get('standard_template', '')}\n"
                f"- 必备要素：{r.get('key_elements', '')}\n"
                f"- 常见问题：{r.get('common_issues', '')}\n"
                f"- 审查要点：{r.get('review_points', '')}"
            )
        else:
            parts.append("（标准模板库中暂无匹配该条款类别的示范模板）")

    return "\n\n".join(parts)
