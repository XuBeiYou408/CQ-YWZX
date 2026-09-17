"""
智审 (Doc-Agent) - 感知层条款结构化切分器
混合拆条策略：
  1. 正则拆条（纯离线、零模型开销）：支持「第X条」「一、」「1.1」三种子层级
  2. LLM 兜底拆条：正则拆不出（纯文本合同 < 3 条）时，由 agent 层调用模型辅助
产出结构化条款清单（含 char_range 原文回溯区间 + 轻量风险信号 + 候选标签），
这是 Agent「逐条分诊决策」的物理前提。

感知层产出边界：只回答「这里有哪几条、各自长什么样、可能涉及什么」，
不回答「有没有风险」——那是规划层的职责。
"""

import re
from typing import Any, Dict, List, Optional

# 条款起始行识别：第X条 / 一、 / 1.1 / （一） / （1）
_HEAD_ARTICLE = re.compile(r"^\s*第[零〇一二三四五六七八九十百千两\d]+\s*[条章款篇部节]")
_HEAD_CN_ENUM = re.compile(r"^\s*[一二三四五六七八九十]+\s*[、．.]")
_HEAD_NUM_ENUM = re.compile(r"^\s*\d{1,2}(?:\.\d{1,2}){0,2}\s*[、．.\)]\s*")
_HEAD_PAREN_ENUM = re.compile(r"^\s*[（(](?:[零〇一二三四五六七八九十百千两\d]{1,3})[）)]")

_BOILERPLATE_RE = re.compile(
    r"保密|通知|不可抗力|争议|管辖|附则|其他|未尽事宜|完整协议|签署|落款|生效"
)

_OBLIGATION_VERBS = [
    "支付", "赔偿", "承担", "负责", "应当", "不得", "有权", "解除",
    "免除", "放弃", "转让", "归属", "独家", "永久", "无偿", "验收", "违约",
]

_AMOUNT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*[%％‰]|[一二三五十百]+(?:点[零一二三四五六七八九])?%"
    r"|日万分之|万分之|千分之|年化"
)
_DURATION_RE = re.compile(r"\d+\s*(?:个)?\s*(?:日|天|月|年|工作日)")


def _is_heading(line: str, level: str = "any") -> bool:
    """判断一行是否为条款起始标题行（level 指定标题层级）"""
    s = line.strip()
    if not s:
        return False
    # 第X条 / 第X章 层级：即便标题与正文同行（整行很长），依然是坚实的条款起始标志
    if level in ("any", "article") and _HEAD_ARTICLE.match(s):
        return True
    # 「一、」与「（一）/（1）」层级：若行在合理长度内（<= 80）或后跟标点/空格，认作条款起点
    if level in ("any", "cn"):
        if _HEAD_CN_ENUM.match(s) and (len(s) <= 80 or re.search(r"^[一二三四五六七八九十]+\s*[、．.][^\s。；:：\n]+[。；:：\s]", s)):
            return True
        if _HEAD_PAREN_ENUM.match(s) and (len(s) <= 80 or re.search(r"^[（(](?:[零〇一二三四五六七八九十百千两\d]{1,3})[）)][^\s。；:：\n]+[。；:：\s]", s)):
            return True
    # 「1.1」/「1、」数字层级：若行合理（<= 70）或有明确标题分隔，认作条款起点
    if level in ("any", "num"):
        if _HEAD_NUM_ENUM.match(s) and (len(s) <= 70 or re.search(r"^\d{1,2}(?:\.\d{1,2}){0,2}\s*[、．.\)]\s*[^\s。；:：\n]+[。；:：\s]", s)):
            return True
    return False


def _extract_signals(heading: str, text: str) -> Dict[str, Any]:
    """提取轻量风险线索（给规划层看的 hint，不是判定结论）"""
    amount_like = _AMOUNT_RE.findall(text)
    obligation_verbs = [v for v in _OBLIGATION_VERBS if v in text][:8]
    durations = _DURATION_RE.findall(text)[:6]
    is_standard_boilerplate = bool(
        _BOILERPLATE_RE.search(heading or "") and len(text) < 400
    )
    suspicious = bool(
        amount_like
        or any(k in text for k in ["无条件", "单方", "独家", "永久", "免除", "概不负责", "视为"])
    )
    return {
        "amount_like": amount_like[:6],
        "obligation_verbs": obligation_verbs,
        "durations": durations,
        "is_standard_boilerplate": is_standard_boilerplate,
        "suspicious": suspicious,
    }


def _candidate_labels(heading: str, text: str, signals: Dict[str, Any]) -> List[str]:
    """基于信号与关键词的候选标签预标（非结论，仅供规划层参考）"""
    labels = []
    if ("违约金" in text or "惩罚" in text) and signals["amount_like"]:
        labels.append("违约金畸高候选")
    if "免责" in text or "不承担" in text or "概不负责" in text:
        labels.append("单方免责候选")
    if "解除" in text and ("随时" in text or "无条件" in text or "单方" in text):
        labels.append("单方解除权候选")
    if re.search(r"知识产权|所有权|著作权|专利|源码|归属", text):
        labels.append("权属归属候选")
    if "验收" in text and any(d.endswith(("日", "工作日")) and int(re.sub(r"\D", "", d) or 0) >= 30 for d in signals["durations"]):
        labels.append("验收异常候选")
    if "利息" in text or "年化" in text or "利率" in text:
        labels.append("利率上限候选")
    if "保密" in text and ("永久" in text or "无限" in text):
        labels.append("保密范围泛化候选")
    return labels[:3]


def split_clauses(contract_text: str) -> List[Dict[str, Any]]:
    """
    正则条款切分（纯离线），层级优先级策略：
      1. 「第X条」层级优先（子编号 1.1/2.1 并入父条款，不碎片化）
      2. 拆不出 → 回退「一、／（一）／（1）」层级
      3. 仍拆不出 → 回退「1.1」数字层级
      4. 各层级取有效条款（>= 1 条）
    """
    if not contract_text or not contract_text.strip():
        return []

    lines = contract_text.splitlines(keepends=True)

    for level in ("article", "cn", "num"):
        starts: List[int] = [
            i for i, line in enumerate(lines) if _is_heading(line, level=level)
        ]
        if len(starts) >= 1:
            built = _build_clauses(lines, starts)
            if built:
                return built

    # 各层级均未命中的混合/宽松判定：
    starts = [i for i, line in enumerate(lines) if _is_heading(line, level="any")]
    if starts:
        built = _build_clauses(lines, starts)
        if built:
            return built

    return []


def _build_clauses(lines: List[str], starts: List[int]) -> List[Dict[str, Any]]:
    clauses: List[Dict[str, Any]] = []
    n = len(lines)
    for idx, start_idx in enumerate(starts):
        end_idx = starts[idx + 1] if idx + 1 < len(starts) else n

        head_line = lines[start_idx].rstrip("\r\n")
        raw_head = head_line.strip()

        # 提炼条款标题：如果标题行混有正文段落（长度超过 40 字），截取至首个断句标点或空格
        heading = raw_head
        if len(raw_head) > 40:
            m = re.match(
                r"^(\s*(?:第[零〇一二三四五六七八九十百千两\d]+\s*[条章款篇部节]|[一二三四五六七八九十]+\s*[、．.]|[（(][^）)]+[）)]|\d{1,2}(?:\.\d{1,2}){0,2}\s*[、．.\)])\s*[^。；;：:\t\n\r]+)",
                raw_head
            )
            if m:
                heading = m.group(1).strip()
            else:
                heading = raw_head[:40]
        heading = heading.rstrip("。；;：:\t ").strip()

        # 第X条 标题行往往自带条款名（如「第七条 违约责任」）
        body_lines = lines[start_idx + 1:end_idx]
        body = "".join(body_lines).strip()

        # char_range：条款在原文中的字符区间（含标题行）
        char_start = sum(len(l) for l in lines[:start_idx])
        clause_len = sum(len(l) for l in lines[start_idx:end_idx])
        char_end = char_start + clause_len

        full_text = (head_line + "\n" + body).strip() if body else raw_head
        # 附加条款正文（把标题并入 text，保证 char_range 与 text 对齐）
        text = full_text

        signals = _extract_signals(heading, text)
        labels = _candidate_labels(heading, text, signals)

        # 极短条款（如孤立标题行）且后面没有内容 → 合并跳过（除非只有这一条）
        if len(text) < 8 and len(starts) > 1 and idx + 1 < len(starts):
            continue

        clauses.append({
            "clause_id": f"C{idx + 1:02d}",
            "index": idx + 1,
            "heading": heading[:60],
            "text": text,
            "char_range": [char_start, char_end],
            "signals": signals,
            "candidate_labels": labels,
        })

    # 重新编号（可能有被跳过的条目）
    for i, c in enumerate(clauses, start=1):
        c["clause_id"] = f"C{i:02d}"
        c["index"] = i

    return clauses


def clauses_from_llm_output(items: List[Dict[str, Any]], original_text: str) -> List[Dict[str, Any]]:
    """
    将 LLM 兜底拆条输出（[{heading, text}, ...]）转换为标准条款结构，
    并尽力在原文中回溯定位 char_range（找不到则置 None，前端高亮降级为无定位）。
    """
    clauses: List[Dict[str, Any]] = []
    search_from = 0
    for i, item in enumerate(items, start=1):
        heading = str(item.get("heading") or f"第{i}部分").strip()[:60]
        text = str(item.get("text") or "").strip()
        if not text:
            continue

        char_range = None
        probe = text[:60]
        pos = original_text.find(probe, search_from) if probe else -1
        if pos >= 0:
            char_range = [pos, pos + len(text)]
            search_from = pos + 1

        signals = _extract_signals(heading, text)
        clauses.append({
            "clause_id": f"C{i:02d}",
            "index": i,
            "heading": heading,
            "text": text,
            "char_range": char_range,
            "signals": signals,
            "candidate_labels": _candidate_labels(heading, text, signals),
        })
    return clauses


def clauses_summary_for_prompt(clauses: List[Dict[str, Any]], max_chars_per_clause: int = 600) -> str:
    """将条款清单压缩为规划 Prompt 可用的摘要文本"""
    parts = []
    for c in clauses:
        text = c["text"][:max_chars_per_clause]
        if len(c["text"]) > max_chars_per_clause:
            text += "…（截断）"
        sig = c["signals"]
        hints = []
        if sig["amount_like"]:
            hints.append("金额类:" + "/".join(sig["amount_like"][:3]))
        if sig["suspicious"]:
            hints.append("含可疑信号")
        if sig["is_standard_boilerplate"]:
            hints.append("疑似常规模板条款")
        if c["candidate_labels"]:
            hints.append("候选标签:" + ",".join(c["candidate_labels"]))
        hint_str = f"（线索：{'；'.join(hints)}）" if hints else ""
        parts.append(f"- [{c['clause_id']}] {c['heading']}{hint_str}\n  正文：{text}")
    return "\n".join(parts)
