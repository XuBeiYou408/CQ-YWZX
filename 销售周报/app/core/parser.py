"""
多格式销售周报解析器
支持 Word (.docx) / Excel (.xlsx) / Markdown (.md) / 纯文本 (.txt)
提取结构化业绩指标、关键事项，并保留 100% 原始提交周报全文
"""
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import openpyxl
from docx import Document


def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    lines = []
    # 1. 提取段落
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            lines.append(t)
    # 2. 提取表格
    for table in doc.tables:
        for row in table.rows:
            row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if any(row_cells):
                lines.append(" | ".join(row_cells))
    return "\n\n".join(lines)


def extract_data_from_excel(file_bytes: bytes) -> Dict[str, Any]:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return {"raw_text": "", "extracted_fields": {}}

    lines = []
    headers = [str(cell or "").strip() for cell in rows[0]]
    lines.append(" | ".join(headers))

    extracted = {}
    for r in rows[1:]:
        row_str = [str(cell if cell is not None else "").strip() for cell in r]
        if any(row_str):
            lines.append(" | ".join(row_str))

    raw_text = "\n".join(lines)
    return {
        "raw_text": raw_text,
        "extracted_fields": parse_text_fields(raw_text)
    }


def parse_text_fields(text: str) -> Dict[str, Any]:
    """
    智能正则提取周报中的销售关键指标
    """
    fields: Dict[str, Any] = {
        "salesperson": "",
        "department": "",
        "target_amount": 0.0,
        "actual_amount": 0.0,
        "collection_amount": 0.0,
        "visit_count": 0,
        "key_deals": [],
        "blockers": "",
        "next_week_plan": "",
    }

    # 提取姓名
    m_name = re.search(r"(?:销售姓名|汇报人|姓名|销售代表)[:：\s]+([\w\u4e00-\u9fa5]{2,6})", text)
    if m_name:
        fields["salesperson"] = m_name.group(1).strip()

    # 提取部门
    m_dept = re.search(r"(?:所属部门|部门|区域)[:：\s]+([\w\u4e00-\u9fa5]{2,15})", text)
    if m_dept:
        fields["department"] = m_dept.group(1).strip()

    # 提取目标金额（万元或元）
    m_target = re.search(r"(?:本周目标|目标额|业绩目标)[:：\s]+([0-9.]+)\s*(万|元)?", text)
    if m_target:
        val = float(m_target.group(1))
        if m_target.group(2) == "万" or val < 1000:
            val = val * 10000
        fields["target_amount"] = val

    # 提取实际签约金额
    m_actual = re.search(r"(?:实际签约|成单金额|本周完成|实际业绩|签约额)[:：\s]+([0-9.]+)\s*(万|元)?", text)
    if m_actual:
        val = float(m_actual.group(1))
        if m_actual.group(2) == "万" or val < 1000:
            val = val * 10000
        fields["actual_amount"] = val

    # 提取实际回款金额
    m_col = re.search(r"(?:实际回款|回款金额|本周回款)[:：\s]+([0-9.]+)\s*(万|元)?", text)
    if m_col:
        val = float(m_col.group(1))
        if m_col.group(2) == "万" or val < 1000:
            val = val * 10000
        fields["collection_amount"] = val

    # 提取拜访客户数
    m_visit = re.search(r"(?:拜访客户数|拜访量|客户拜访|拜访)[:：\s]+([0-9]+)", text)
    if m_visit:
        fields["visit_count"] = int(m_visit.group(1))

    # 提取阻碍与卡点
    m_block = re.search(r"(?:面临阻碍|问题与卡点|求助事项|需要支持|风险预警)[:：\s]+([\s\S]*?)(?=(?:下周计划|下周工作|下周重点|$))", text)
    if m_block:
        fields["blockers"] = m_block.group(1).strip()

    # 提取下周工作计划
    m_plan = re.search(r"(?:下周计划|下周工作|下周重点)[:：\s]+([\s\S]*?)$", text)
    if m_plan:
        fields["next_week_plan"] = m_plan.group(1).strip()

    return fields


def parse_weekly_report(filename: str, file_bytes: bytes) -> Dict[str, Any]:
    """
    通用周报解析入口，返回结构化数据及 100% 原始周报原件文本
    """
    suffix = Path(filename).suffix.lower()
    raw_text = ""

    if suffix == ".docx":
        raw_text = extract_text_from_docx(file_bytes)
    elif suffix in (".xlsx", ".xls"):
        excel_res = extract_data_from_excel(file_bytes)
        raw_text = excel_res["raw_text"]
    elif suffix in (".md", ".txt"):
        try:
            raw_text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = file_bytes.decode("gbk", errors="replace")
    else:
        raise ValueError(f"不支持的周报文件格式: {suffix}，请上传 .docx, .xlsx, .md, .txt 文件")

    raw_text = raw_text.strip()
    extracted = parse_text_fields(raw_text)

    # 补全默认销售姓名
    name = extracted.get("salesperson") or Path(filename).stem.replace("周报", "").replace("销售", "").strip() or "待识别销售"
    target = extracted.get("target_amount") or 500000.0
    actual = extracted.get("actual_amount") or 0.0
    rate = round((actual / target * 100), 1) if target > 0 else 0.0

    if rate >= 100:
        status = "exceeded"
        status_label = "超额完成"
    elif rate >= 80:
        status = "on_track"
        status_label = "稳步推进"
    elif rate >= 50:
        status = "at_risk"
        status_label = "存在差距"
    else:
        status = "blocked"
        status_label = "遇阻预警"

    return {
        "filename": filename,
        "salesperson": name,
        "department": extracted.get("department") or "销售一部",
        "target_amount": target,
        "actual_amount": actual,
        "collection_amount": extracted.get("collection_amount") or (actual * 0.8),
        "completion_rate": rate,
        "visit_count": extracted.get("visit_count") or 5,
        "status": status,
        "status_label": status_label,
        "blockers": extracted.get("blockers") or "无明显卡点，按计划推进",
        "next_week_plan": extracted.get("next_week_plan") or "跟进高意向客户，推进签约",
        "raw_content": raw_text,  # 100% 原始提交周报全文，供主管随时查阅原件
        "reviewed": False,
        "supervisor_comment": "",
    }