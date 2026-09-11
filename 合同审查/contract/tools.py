"""
智审 (Doc-Agent) - Agent 行动层工具注册表与 JSON 协议执行器
核心认知：当前系统缺的不是能力，而是工具的封装与可调用性。
本模块把既有能力包装为模型可自主调用的 5 个工具：

  precedent_search  按具体风险点检索最高法判例（precedents.py）
  gate_check        按需取指定专项门禁核查要点（gates/special_gates.py）
  statute_lookup    检索法条原文（statutes.py，新建）
  clause_rewrite    条款级合规改写参考（rule_cards.py + 标准条款字典）
  rule_scan         规则引擎条款级扫描（rule_cards.py，兜底工具）

调用协议（B 方案：JSON 协议模拟，不依赖模型原生 function calling）：
  模型输出 <tool_call>{"name": "...", "args": {...}}</tool_call>
  → 本执行器解析并执行 → 结果以 <tool_result> 回灌 → 模型继续推理

严禁在 Python 侧写死调用剧本——「哪条要查、查几次」由模型决定。
"""

import csv
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

from contract.precedents import search_by_risk_point
from contract.gates.special_gates import get_gate_by_name, list_gate_names, route_special_gates
from contract.statutes import search_statutes, format_statute_for_prompt
from contract.rule_cards import scan_rules, render_rule_card


# ---------------------------------------------------------------------------
# 标准条款字典（数据源：contract/data/clause_standards.csv）
# ---------------------------------------------------------------------------
_STANDARDS_PATH = os.path.join(os.path.dirname(__file__), "data", "clause_standards.csv")
_STANDARDS_CACHE: Optional[List[Dict[str, str]]] = None


def _load_standards() -> List[Dict[str, str]]:
    global _STANDARDS_CACHE
    if _STANDARDS_CACHE is not None:
        return _STANDARDS_CACHE
    rows: List[Dict[str, str]] = []
    try:
        with open(_STANDARDS_PATH, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        rows = []
    _STANDARDS_CACHE = rows
    return rows


def _match_standard(clause_text: str) -> Optional[Dict[str, str]]:
    """在标准条款字典中为条款寻找最匹配的示范模板"""
    best, best_score = None, 0
    for row in _load_standards():
        score = 0
        ct = row.get("clause_type", "")
        if ct and ct[:2] in clause_text:
            score += 2
        for elem in re.split(r"[、，,]", row.get("key_elements", "")):
            elem = elem.strip()
            if elem and elem in clause_text:
                score += 2
        for issue in re.split(r"[、，,]", row.get("common_issues", "")):
            issue = issue.strip()
            if issue and issue[:4] in clause_text:
                score += 1
        if score > best_score:
            best, best_score = row, score
    return best if best_score >= 2 else None


# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------
TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "precedent_search": {
        "desc": "按具体风险点检索最高人民法院指导案例与裁判要旨。args: {\"query\": \"风险点描述\", \"top_k\": 3}",
        "fn": lambda args: _tool_precedent_search(args),
    },
    "gate_check": {
        "desc": f"取专项门禁核查要点。可传门禁名（如 {', '.join(list_gate_names()[:5])} 等）或条款文本自动路由。args: {{\"gate_name\": \"...\"}} 或 {{\"clause_text\": \"...\"}}",
        "fn": lambda args: _tool_gate_check(args),
    },
    "statute_lookup": {
        "desc": "检索法条原文（民法典/劳动法/民诉法等）。args: {\"keyword\": \"关键词或条文主题\", \"top_k\": 3}",
        "fn": lambda args: _tool_statute_lookup(args),
    },
    "clause_rewrite": {
        "desc": "获取条款的合规改写参考（标准条款示范模板 + 规则引擎修改建议）。args: {\"clause_text\": \"待改写条款原文\"}",
        "fn": lambda args: _tool_clause_rewrite(args),
    },
    "rule_scan": {
        "desc": "离线规则引擎条款级高危扫描（兜底工具）。args: {\"clause_text\": \"待扫描条款原文\"}",
        "fn": lambda args: _tool_rule_scan(args),
    },
}


def _tool_precedent_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("query") or args.get("keyword") or "")[:500]
    top_k = int(args.get("top_k") or 3)
    top_k = max(1, min(top_k, 5))
    results = search_by_risk_point(query, top_k=top_k)
    blocks = []
    for p in results:
        blocks.append(
            f"- 🏛️ {p['title']} ({p.get('case_no', '')})\n"
            f"  法条：{p.get('statute', '')}\n"
            f"  裁判要旨：{p['key_holding']}\n"
            f"  实务建议：{p.get('practical_advice', '')}"
        )
    return {
        "ok": True,
        "result_summary": f"命中 {len(results)} 项判例：" + "；".join(p["title"] for p in results),
        "data": results,
        "prompt_text": "\n".join(blocks) if blocks else "未命中相关判例，请换用更具体的风险点关键词重试。",
    }


def _tool_gate_check(args: Dict[str, Any]) -> Dict[str, Any]:
    gate_name = args.get("gate_name")
    clause_text = str(args.get("clause_text") or "")[:2000]
    if gate_name:
        gate = get_gate_by_name(str(gate_name))
        if not gate:
            return {
                "ok": False,
                "result_summary": f"未找到名为「{gate_name}」的门禁。可用门禁：{', '.join(list_gate_names())}",
                "prompt_text": "",
            }
    else:
        matched = route_special_gates(clause_text, "")
        if not matched:
            return {
                "ok": True,
                "result_summary": "该条款未命中任何专项门禁（常规条款）",
                "prompt_text": "该条款未命中专项门禁，按通用商业合同常规要点核验即可。",
            }
        gate = matched[0]
    pts = "\n".join(f"  - {cp}" for cp in gate["checkpoints"])
    return {
        "ok": True,
        "result_summary": f"已取用门禁【{gate['title']}】共 {len(gate['checkpoints'])} 项核查要点",
        "prompt_text": f"【{gate['title']}】核查要点：\n{pts}",
    }


def _tool_statute_lookup(args: Dict[str, Any]) -> Dict[str, Any]:
    keyword = str(args.get("keyword") or args.get("query") or "")[:200]
    top_k = max(1, min(int(args.get("top_k") or 3), 5))
    results = search_statutes(keyword, top_k=top_k)
    if not results:
        return {
            "ok": True,
            "result_summary": f"未检索到与「{keyword}」相关的法条",
            "prompt_text": f"法条库中未检索到「{keyword}」相关条文，请引用你确有把握的条文，切勿编造。",
        }
    prompt_text = "\n".join(format_statute_for_prompt(st) for st in results)
    return {
        "ok": True,
        "result_summary": f"检索到 {len(results)} 项法条：" + "；".join(f"《{st['law']}》{st['article']}" for st in results),
        "prompt_text": prompt_text,
    }


def _tool_clause_rewrite(args: Dict[str, Any]) -> Dict[str, Any]:
    clause_text = str(args.get("clause_text") or "")[:2000]
    if not clause_text.strip():
        return {"ok": False, "result_summary": "clause_text 不能为空", "prompt_text": ""}

    parts: List[str] = []

    # 1. 规则引擎沉淀的修改建议（对高危模式条款给出定稿级建议）
    hits = scan_rules(clause_text)
    for h in hits:
        parts.append(f"规则引擎识别【{h['title']}】，建议改写为：\n“{h['suggestion']}”")

    # 2. 标准条款示范模板
    std = _match_standard(clause_text)
    if std:
        parts.append(
            f"标准条款示范模板（{std.get('clause_type', '')}·{std.get('contract_type', '')}）：\n"
            f"“{std.get('standard_template', '')}”\n"
            f"要素清单：{std.get('key_elements', '')}；常见问题：{std.get('common_issues', '')}"
        )

    if not parts:
        return {
            "ok": True,
            "result_summary": "未命中规则模板与标准字典，请依据《民法典》对等原则自行起草修改建议",
            "prompt_text": "该条款未命中内置模板。请基于《民法典》权利义务对等原则与商业惯例，直接起草合规修改建议初稿。",
        }
    return {
        "ok": True,
        "result_summary": "已获取合规改写参考（" + "；".join(p.split("：")[0] for p in parts) + "）",
        "prompt_text": "\n\n".join(parts),
    }


def _tool_rule_scan(args: Dict[str, Any]) -> Dict[str, Any]:
    clause_text = str(args.get("clause_text") or "")[:2000]
    hits = scan_rules(clause_text)
    if not hits:
        return {
            "ok": True,
            "result_summary": "规则引擎未命中高危模式",
            "prompt_text": "离线规则引擎未在该条款中命中已知高危模式。",
        }
    blocks = []
    for h in hits:
        card = render_rule_card(h, "“" + clause_text[:150] + "”")
        blocks.append(f"#### 🔴 [高危风险·规则兜底] {h['title']}\n{card}")
    return {
        "ok": True,
        "result_summary": f"规则引擎命中 {len(hits)} 项高危模式：" + "；".join(h["title"] for h in hits),
        "prompt_text": "\n\n".join(blocks),
    }


# ---------------------------------------------------------------------------
# JSON 协议解析与宽松 JSON 容错（三级：严格解析 → 块抽取 → None 交由上层重试/回退）
# ---------------------------------------------------------------------------
TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*([\s\S]*?)\s*</tool_call>", re.IGNORECASE
)


def parse_json_lenient(text: str) -> Optional[Any]:
    """
    宽松 JSON 解析（一级+二级容错）：
    1. 直接 json.loads（含去除 ```json 围栏）
    2. 正则抽取首个平衡的 {...} 或 [...] 块再解析
    解析失败返回 None（由调用方决定重试或规则回退，即第三级容错）。
    """
    if not text:
        return None
    s = text.strip()

    # 去除 <think> 块与围栏
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"</?think>", "", s).strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
    if fence:
        s = fence.group(1).strip()

    # 一级：直接解析
    try:
        return json.loads(s)
    except Exception:
        pass

    # 一级半：修复模型误输出的双花括号（{{"a": 1}} → {"a": 1}）
    # 部分模型会模仿 Prompt 模板里被转义的 {{ }} 写法，导致 JSON 畸形
    if "{{" in s or "}}" in s:
        s = s.replace("{{", "{").replace("}}", "}")
        try:
            return json.loads(s.strip().strip("`").strip())
        except Exception:
            pass

    # 二级：抽取平衡块
    for opener, closer in (("{", "}"), ("[", "]")):
        start = s.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(s)):
            ch = s[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = s[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
    return None


def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    """解析模型输出中的全部 <tool_call> 块，返回 [{name, args}]"""
    calls: List[Dict[str, Any]] = []
    for m in TOOL_CALL_RE.finditer(text or ""):
        payload = parse_json_lenient(m.group(1))
        if isinstance(payload, dict) and payload.get("name"):
            calls.append({
                "name": str(payload["name"]),
                "args": payload.get("args") or payload.get("arguments") or {},
            })
        elif isinstance(payload, dict) and payload.get("tool"):
            calls.append({
                "name": str(payload["tool"]),
                "args": payload.get("args") or {},
            })
    return calls


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """执行单个工具调用，任何异常都包装为可回灌模型的错误结果（不中断主循环）"""
    spec = TOOL_REGISTRY.get(name)
    if not spec:
        return {
            "ok": False,
            "result_summary": f"未知工具「{name}」。可用工具：{', '.join(TOOL_REGISTRY.keys())}",
            "prompt_text": "",
        }
    try:
        if not isinstance(args, dict):
            args = {}
        return spec["fn"](args)
    except Exception as e:
        return {
            "ok": False,
            "result_summary": f"工具 {name} 执行异常: {type(e).__name__}: {e}",
            "prompt_text": "",
        }


def format_tool_specs_for_prompt() -> str:
    """生成注入 Prompt 的工具说明书"""
    lines = ["你可自主调用以下工具（每个工具每条款最多调用 3 次，先取证再下结论）："]
    for name, spec in TOOL_REGISTRY.items():
        lines.append(f"- {name}: {spec['desc']}")
    lines.append(
        "调用方式：在回复中输出 <tool_call>{\"name\": \"工具名\", \"args\": {...}}</tool_call>，"
        "系统会执行工具并把结果回灌给你。"
        "注意：涉及具体法条与判例引用时，优先调用 statute_lookup / precedent_search 核验原文，"
        "避免仅凭记忆引用；取证充分后立即输出最终结论，不要重复调用同一工具。"
    )
    return "\n".join(lines)
