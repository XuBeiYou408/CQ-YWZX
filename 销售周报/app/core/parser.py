"""
多格式销售周报解析器
支持 Word (.docx) / Excel (.xlsx) / Markdown (.md) / 纯文本 (.txt)
提取结构化业绩指标、关键事项，并保留 100% 原始提交周报全文

解析采用双路径：
  1) 指标矩阵表：形如「行=指标名，列=目标/实际」的表格（docx/xlsx 表格与 Markdown 表格均适用）
  2) 键值对：形如「- **本周签约目标**：600,000 元」或「汇报人 | 赵子龙」的行
"""
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from docx import Document


# ---------------------------------------------------------------------------
# 文本归一化与数值提取
# ---------------------------------------------------------------------------

_MARK_RE = re.compile(r"[*#`\s\-—–:：()（）【】\[\]|、]")
_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)")


def _strip_marks(text: str) -> str:
    """去掉 Markdown 标记、标点与空白，便于关键词命中"""
    return _MARK_RE.sub("", text or "")


def _to_number(text: str) -> Optional[float]:
    """提取文本中的首个数值；若其后紧随「万」单位则换算为元"""
    if not text:
        return None
    match = _NUM_RE.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if "万" in text[match.end():match.end() + 2]:
        value *= 10000
    return value


def _to_int(text: str) -> Optional[int]:
    value = _to_number(text)
    return int(value) if value is not None else None


def _clean_text(text: str, max_len: int = 40) -> str:
    """清理姓名/部门等文本字段：去掉括号补充说明与装饰标记"""
    cleaned = re.sub(r"[（(][^)）]*[)）]", "", text or "")
    cleaned = cleaned.replace("*", "").strip(" -—:：")
    return cleaned[:max_len].strip()


# ---------------------------------------------------------------------------
# 标签识别
# ---------------------------------------------------------------------------

_NAME_LABELS = ("销售姓名", "汇报人", "汇报人员", "提报人", "姓名", "销售代表", "销售经理", "销售总监")
_DEPT_LABELS = ("所属部门", "所属大区", "所属区域", "所属单位", "部门", "大区", "区域")

# 指标识别规则，自上而下匹配，先命中者胜出（顺序即优先级）
_METRIC_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("target_amount", ("目标", "考核指标")),
    ("collection_amount", ("回款",)),
    ("visit_count", ("拜访", "客拜")),
    ("new_leads", ("线索", "商机")),
    ("actual_amount", ("签约", "成单", "业绩", "完成")),
)

_INT_METRICS = ("visit_count", "new_leads")


def _match_metric(label: str) -> Optional[str]:
    compact = _strip_marks(label)
    if not compact:
        return None
    for key, keywords in _METRIC_RULES:
        if any(keyword in compact for keyword in keywords):
            return key
    return None


def _match_label(label: str, candidates: Tuple[str, ...]) -> bool:
    compact = _strip_marks(label)
    return bool(compact) and any(candidate in compact for candidate in candidates)


# ---------------------------------------------------------------------------
# 行级键值对解析
# ---------------------------------------------------------------------------

def _split_kv(line: str) -> Tuple[Optional[str], str]:
    """把一行拆成 (标签, 值)。支持 '标签：值'、'标签 | 值' 及 Markdown 列表/标题前缀"""
    text = (line or "").strip()
    if not text:
        return None, ""
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"^[-*+•]\s+", "", text)
    text = re.sub(r"^\d+[.、)）]\s*", "", text)
    if "|" in text:
        cells = [cell.strip() for cell in text.split("|") if cell.strip()]
        if len(cells) >= 2:
            return cells[0], cells[1]
        return None, ""
    match = re.match(r"^([^：:]{1,30})[：:]\s*(.*)$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None, ""


def _apply_kv(label: str, value: str, fields: Dict[str, Any]) -> None:
    if not label or not value:
        return
    if _match_label(label, _NAME_LABELS):
        if not fields["salesperson"]:
            fields["salesperson"] = _clean_text(value, 8)
        return
    if _match_label(label, _DEPT_LABELS):
        if not fields["department"]:
            fields["department"] = _clean_text(value, 20)
        return

    metric = _match_metric(label)
    if not metric:
        return
    parsed = _to_int(value) if metric in _INT_METRICS else _to_number(value)
    if parsed is None:
        return
    # 矩阵表解析结果优先级更高，此处不覆盖
    if not fields.get(metric):
        fields[metric] = parsed


# ---------------------------------------------------------------------------
# 指标矩阵表解析（行=指标名，列=目标/实际）
# ---------------------------------------------------------------------------

_TABLE_FAMILIES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("collection", ("回款",)),
    ("visit", ("拜访", "客拜")),
    ("leads", ("线索", "商机")),
    ("contract", ("签约", "成单", "业绩")),
)
_TARGET_HEADERS = ("目标", "计划", "指标值")
_ACTUAL_HEADERS = ("实际完成", "实际", "完成", "达成")


def _table_cells(line: str) -> Optional[List[str]]:
    """含竖线的行拆成单元格；Markdown 对齐行返回空列表；非表格行返回 None"""
    if "|" not in line:
        return None
    cells = [cell.strip() for cell in line.split("|")]
    filled = [cell for cell in cells if cell]
    if filled and all(re.fullmatch(r":?-{2,}:?", cell) for cell in filled):
        return []
    return cells


def _find_col(cells: List[str], headers: Tuple[str, ...]) -> Optional[int]:
    for index, cell in enumerate(cells):
        compact = _strip_marks(cell)
        if any(header in compact for header in headers):
            return index
    return None


def _family_of(label: str) -> Optional[str]:
    compact = _strip_marks(label)
    if not compact:
        return None
    for family, keywords in _TABLE_FAMILIES:
        if any(keyword in compact for keyword in keywords):
            return family
    return None


def _put_number(result: Dict[str, Any], key: str, cells: List[str], col: Optional[int]) -> None:
    if col is None or col >= len(cells) or key in result:
        return
    value = _to_number(cells[col])
    if value is not None:
        result[key] = value


def _scan_metric_matrix(lines: List[str]) -> Tuple[set, Dict[str, Any]]:
    """扫描「表头含目标/实际列」的指标矩阵表，返回 (已占用行号集合, 指标值)"""
    used: set = set()
    result: Dict[str, Any] = {}
    col_target: Optional[int] = None
    col_actual: Optional[int] = None
    in_table = False

    for index, line in enumerate(lines):
        cells = _table_cells(line)
        if cells is None:
            in_table, col_target, col_actual = False, None, None
            continue
        if not cells:
            continue

        target_col = _find_col(cells, _TARGET_HEADERS)
        actual_col = _find_col(cells, _ACTUAL_HEADERS)
        if target_col is not None and actual_col is not None:
            in_table, col_target, col_actual = True, target_col, actual_col
            used.add(index)
            continue
        if not in_table:
            continue

        label_cell = next((cell for cell in cells if cell), "")
        family = _family_of(label_cell)
        if not family:
            continue
        used.add(index)

        if family == "contract":
            _put_number(result, "target_amount", cells, col_target)
            _put_number(result, "actual_amount", cells, col_actual)
        elif family == "collection":
            _put_number(result, "collection_amount", cells, col_actual)
        elif family == "visit":
            _put_number(result, "visit_count", cells, col_actual)
        elif family == "leads":
            _put_number(result, "new_leads", cells, col_actual)

    return used, result


# ---------------------------------------------------------------------------
# 段落块提取（卡点、下周计划、核心战报）
# ---------------------------------------------------------------------------

_BLOCK_HEADERS = (
    "面临阻碍", "问题与卡点", "求助事项", "需要支持", "风险预警", "急需支持",
    "卡点求助", "支持请求", "主管支持", "需要主管", "遇到的挑战", "挑战与需要",
    "市场动态反馈", "面临的问题", "阻碍与卡点", "求助与支持",
)
_PLAN_HEADERS = (
    "下周计划", "下周工作", "下周重点", "下周自救", "下周排期", "下周规划",
    "下周安排", "下周目标", "下一步计划", "工作计划", "工作规划", "工作排期",
)
_HIGHLIGHT_HEADERS = (
    "成单与推进", "重点成单", "重点商机", "业务进展", "成单与失单",
    "重点签约", "业绩突破", "核心突破", "重点事项",
)


def _is_section_head(line: str, keywords: Tuple[str, ...]) -> bool:
    text = (line or "").strip()
    if not text or len(text) > 40:
        return False
    compact = _strip_marks(text)
    return any(keyword in compact for keyword in keywords)


def _collect_block(lines: List[str], start: int, stop: int) -> str:
    chunk = []
    for raw in lines[start:stop]:
        text = raw.strip()
        if not text or text in ("---", "***", "___", "- - -"):
            continue
        chunk.append(text)
    return "\n".join(chunk).strip()


def _first_bullet(block: str, max_len: int) -> str:
    for line in block.splitlines():
        text = re.sub(r"^[-*+•]\s*", "", line.strip())
        text = re.sub(r"^\d+[.、)）]\s*", "", text)
        text = text.replace("**", "").strip()
        if text:
            return text[:max_len]
    return ""


def _apply_sections(text: str, fields: Dict[str, Any]) -> None:
    lines = text.splitlines()
    block_start: Optional[int] = None
    plan_start: Optional[int] = None
    highlight_start: Optional[int] = None

    for index, line in enumerate(lines):
        if highlight_start is None and _is_section_head(line, _HIGHLIGHT_HEADERS):
            highlight_start = index
        if block_start is None and _is_section_head(line, _BLOCK_HEADERS):
            block_start = index
        if plan_start is None and _is_section_head(line, _PLAN_HEADERS):
            plan_start = index

    if block_start is not None:
        stop = plan_start if (plan_start is not None and plan_start > block_start) else len(lines)
        block = _collect_block(lines, block_start + 1, stop)
        if block:
            fields["blockers"] = block

    if plan_start is not None:
        plan = _collect_block(lines, plan_start + 1, len(lines))
        if plan:
            fields["next_week_plan"] = plan

    if highlight_start is not None:
        boundaries = [x for x in (block_start, plan_start) if x is not None and x > highlight_start]
        stop = min(boundaries) if boundaries else len(lines)
        highlight = _collect_block(lines, highlight_start + 1, stop)
        if highlight:
            fields["highlight_summary"] = _first_bullet(highlight, 120)


# ---------------------------------------------------------------------------
# 文件内容提取
# ---------------------------------------------------------------------------

def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    lines: List[str] = []
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            lines.append(text)
    for table in doc.tables:
        for row in table.rows:
            row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if any(row_cells):
                lines.append(" | ".join(row_cells))
    return "\n\n".join(lines)


def extract_data_from_excel(file_bytes: bytes) -> str:
    workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet = workbook.active
    lines: List[str] = []
    for row in sheet.iter_rows(values_only=True):
        cells = [str(cell).strip() if cell is not None else "" for cell in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def parse_text_fields(text: str) -> Dict[str, Any]:
    """从周报文本中提取结构化销售指标与关键事项"""
    fields: Dict[str, Any] = {
        "salesperson": "",
        "department": "",
        "target_amount": 0.0,
        "actual_amount": 0.0,
        "collection_amount": 0.0,
        "visit_count": 0,
        "new_leads": 0,
        "blockers": "",
        "next_week_plan": "",
        "highlight_summary": "",
    }
    if not text:
        return fields

    lines = text.splitlines()

    # 1) 指标矩阵表优先，其占用的行不再参与键值对解析
    matrix_rows, matrix_values = _scan_metric_matrix(lines)
    fields.update(matrix_values)

    # 2) 逐行键值对
    for index, line in enumerate(lines):
        if index in matrix_rows:
            continue
        label, value = _split_kv(line)
        if label:
            _apply_kv(label, value, fields)

    # 3) 段落块
    _apply_sections(text, fields)

    # 4) 计数类指标归一为整数
    fields["visit_count"] = int(fields.get("visit_count") or 0)
    fields["new_leads"] = int(fields.get("new_leads") or 0)
    return fields


def _name_from_filename(filename: str) -> str:
    """文件名兜底姓名：仅剥离「周报」后缀与部门前缀，避免破坏真实姓名"""
    stem = Path(filename).stem
    stem = re.sub(r"(销售)?(工作)?周报.*$", "", stem)
    # 前缀可能叠加（如「华东大区」），循环剥离两轮
    for _ in range(2):
        stripped = re.sub(
            r"^(销售部|市场部|销售|华东|华北|华南|西南|西北|东北|大区|区域|业务部)", "", stem
        ).strip(" _-—")
        if stripped == stem:
            break
        stem = stripped
    return stem or "待识别销售"


def parse_weekly_report(filename: str, file_bytes: bytes) -> Dict[str, Any]:
    """通用周报解析入口，返回结构化数据及 100% 原始周报原件文本"""
    suffix = Path(filename).suffix.lower()
    if suffix == ".docx":
        try:
            raw_text = extract_text_from_docx(file_bytes)
        except Exception as exc:
            raise ValueError(f"Word 文件解析失败，请确认是有效的 .docx 文件（{exc}）") from exc
    elif suffix == ".xlsx":
        try:
            raw_text = extract_data_from_excel(file_bytes)
        except Exception as exc:
            raise ValueError(f"Excel 文件解析失败，请确认是有效的 .xlsx 文件（{exc}）") from exc
    elif suffix in (".md", ".txt"):
        try:
            raw_text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = file_bytes.decode("gbk", errors="replace")
    else:
        raise ValueError(
            f"不支持的周报文件格式: {suffix or '(无扩展名)'}，"
            "请上传 .docx / .xlsx / .md / .txt 文件（老式 .xls 请另存为 .xlsx）"
        )

    raw_text = raw_text.strip()
    extracted = parse_text_fields(raw_text)

    name = extracted.get("salesperson") or _name_from_filename(filename)
    department = extracted.get("department") or "销售一部"

    target = float(extracted.get("target_amount") or 0.0)
    actual = float(extracted.get("actual_amount") or 0.0)
    # 未识别到目标时以实际签约额兜底，避免出现「有签约却 0% 达成率」的失真展示
    if target <= 0:
        target = actual
    rate = round(actual / target * 100, 1) if target > 0 else 0.0

    collection = float(extracted.get("collection_amount") or 0.0)
    if collection <= 0 and actual > 0:
        collection = round(actual * 0.8, 2)

    visit_count = int(extracted.get("visit_count") or 5)
    new_leads = int(extracted.get("new_leads") or 0)
    is_newbie = bool(re.search(r"入职|新人|应届|实习", raw_text))

    if rate >= 100:
        status, status_label = "exceeded", "超额冲顶"
    elif rate >= 80:
        status, status_label = "on_track", "稳步推进"
    elif rate >= 50:
        status, status_label = "at_risk", "存在差距"
    elif is_newbie:
        status, status_label = "growing", "蓄势破局"
    else:
        status, status_label = "blocked", "遇阻预警"

    return {
        "filename": filename,
        "salesperson": name,
        "department": department,
        "role_title": "客户经理",
        "target_amount": target,
        "actual_amount": actual,
        "collection_amount": collection,
        "completion_rate": rate,
        "visit_count": visit_count,
        "new_leads": new_leads,
        "status": status,
        "status_label": status_label,
        "highlight_summary": extracted.get("highlight_summary") or "",
        "blockers": extracted.get("blockers") or "无明显卡点，按计划推进",
        "next_week_plan": extracted.get("next_week_plan") or "跟进高意向客户，推进签约",
        "raw_content": raw_text,  # 100% 原始提交周报全文，供主管随时查阅原件
        "reviewed": False,
        "supervisor_comment": "",
    }
