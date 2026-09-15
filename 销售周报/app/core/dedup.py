"""
周报上传去重引擎 + ZIP 压缩包内存解包模块 + 汇报周期识别

去重采用三层判定：
  1) 内容指纹判重：周报全文归一化（去空白）后完全一致 → 跳过（重复上传）；
  2) 同人同期判重：同一销售 + 同一汇报周期 → 覆盖更新（以最新提交为准）；
  3) 同人相似判重：同一销售 + 全文相似度 >= 90%（difflib）→ 跳过：
     - 周期不同时标注「疑似复制上周提交」，供主管甄别。

ZIP 解包全程在内存中完成（不落盘），带 GBK 中文文件名还原、
macOS 目录垃圾过滤、单文件大小与总条目数安全限制。
"""
import hashlib
import io
import re
import zipfile
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 安全与格式约束
# ---------------------------------------------------------------------------

SUPPORTED_SUFFIXES = (".docx", ".xlsx", ".md", ".txt")
ZIP_MAX_ENTRIES = 200          # 单个压缩包最多解析条目数
ZIP_MAX_FILE_SIZE = 50 * 1024 * 1024  # 单文件上限 50MB
SIMILARITY_THRESHOLD = 0.90    # 同人相似判重阈值


# ---------------------------------------------------------------------------
# 内容归一化与指纹
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """去掉全部空白字符，消除排版差异对判重的影响"""
    return re.sub(r"\s+", "", text or "")


def content_fingerprint(raw_text: str) -> str:
    """周报全文归一化指纹（SHA-256）"""
    return hashlib.sha256(normalize_text(raw_text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 汇报周期识别与排序
# ---------------------------------------------------------------------------

_YEAR_WEEK_RES = (
    re.compile(r"(20\d{2})\s*年\s*第?\s*(\d{1,2})\s*周"),
    re.compile(r"(20\d{2})[-/]\s*[Ww](\d{1,2})"),
)
_WEEK_ONLY_RES = (
    re.compile(r"第\s*(\d{1,2})\s*周"),
    re.compile(r"\b[Ww](\d{1,2})\b"),
)
_DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
_PERIOD_RE = re.compile(r"(20\d{2})\s*年\s*第?\s*(\d{1,2})\s*周")


def detect_report_period(filename: str, raw_text: str, today: Optional[date] = None) -> str:
    """
    从文件名与周报正文识别汇报周期，返回 'YYYY年第N周'。
    识别优先级：年+周 > 纯周次（补当前年）> 正文日期（换算 ISO 周）> 当前周兜底。
    """
    now = today or datetime.now().date()
    haystack = f"{filename}\n{(raw_text or '')[:3000]}"

    for pat in _YEAR_WEEK_RES:
        m = pat.search(haystack)
        if m and 1 <= int(m.group(2)) <= 53:
            return f"{int(m.group(1))}年第{int(m.group(2))}周"

    for pat in _WEEK_ONLY_RES:
        m = pat.search(haystack)
        if m and 1 <= int(m.group(1)) <= 53:
            return f"{now.isocalendar()[0]}年第{int(m.group(1))}周"

    for m in _DATE_RE.finditer(haystack):
        try:
            iso = date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isocalendar()
            return f"{iso[0]}年第{iso[1]}周"
        except ValueError:
            continue

    iso = now.isocalendar()
    return f"{iso[0]}年第{iso[1]}周"


def period_sort_key(period: str) -> Tuple[int, int]:
    """周期排序键：'2026年第38周' → (2026, 38)；无法解析 → (0, 0) 排最前"""
    m = _PERIOD_RE.search(period or "")
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)))


# ---------------------------------------------------------------------------
# 去重判定
# ---------------------------------------------------------------------------

def _dup_ref(report: Dict[str, Any]) -> Dict[str, Any]:
    """重复对象摘要，供前端展示命中的是哪份已有周报"""
    return {
        "existing_id": report.get("id", ""),
        "existing_salesperson": report.get("salesperson", "未知"),
        "existing_filename": report.get("filename", ""),
    }


def find_duplicate(
    parsed: Dict[str, Any],
    existing_reports: List[Dict[str, Any]],
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> Optional[Dict[str, Any]]:
    """
    判断一份新解析的周报与已有周报的关系。

    :param parsed: parse_weekly_report 的输出（含 raw_content / salesperson / report_period）
    :param existing_reports: 库内已有周报 + 本批次已加入的周报
    :return:
        None                → 无冲突，正常新增；
        {"action": "skip", ...}    → 重复，跳过入库；
        {"action": "replace", ...} → 同人同期，覆盖更新已有记录。
    """
    new_norm = normalize_text(parsed.get("raw_content", ""))
    if not new_norm:
        return None

    new_name = (parsed.get("salesperson") or "").strip()
    new_period = (parsed.get("report_period") or "").strip()

    for report in existing_reports:
        old_norm = normalize_text(report.get("raw_content", ""))
        if not old_norm:
            continue

        # 第一层：内容指纹完全一致 → 无条件跳过
        if new_norm == old_norm:
            return {
                "action": "skip",
                "reason": "内容完全一致",
                "matched": _dup_ref(report),
            }

        # 以下判定仅对同一销售生效
        if not (new_name and new_name == (report.get("salesperson") or "").strip()):
            continue

        old_period = (report.get("report_period") or "").strip()

        # 第二层：同人同期 → 覆盖更新（以最新提交为准，批阅状态重置）
        if new_period and old_period and new_period == old_period:
            return {
                "action": "replace",
                "reason": f"同人同期（{new_period}）重复提交，已覆盖为最新版",
                "matched": _dup_ref(report),
            }

        # 第三层：同人高相似（快速预筛：长度差异过大直接跳过）
        len_ratio = min(len(new_norm), len(old_norm)) / max(len(new_norm), len(old_norm))
        if len_ratio < similarity_threshold:
            continue
        ratio = SequenceMatcher(None, new_norm, old_norm).ratio()
        if ratio >= similarity_threshold:
            if new_period and old_period and new_period != old_period:
                reason = f"与 {old_period} 周报内容高度雷同（{ratio * 100:.0f}%），疑似复制提交"
            else:
                reason = f"与 {report.get('salesperson', '未知')} 已有周报相似度 {ratio * 100:.0f}%"
            return {
                "action": "skip",
                "reason": reason,
                "matched": _dup_ref(report),
            }

    return None


# ---------------------------------------------------------------------------
# ZIP 压缩包内存解包
# ---------------------------------------------------------------------------

def _decode_zip_name(info: zipfile.ZipInfo) -> str:
    """
    还原压缩包内文件名编码：
    - flag_bits 0x800 表示明确 UTF-8，直接使用；
    - 否则 zipfile 按 cp437 解码，Windows 中文压缩包实为 GBK，需转回。
    """
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        return name.encode("cp437").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _is_junk_entry(name: str) -> bool:
    """过滤 macOS 目录垃圾与隐藏文件"""
    parts = PurePosixPath(name).parts
    return any(part == "__MACOSX" or part.startswith(".") for part in parts)


def extract_zip_entries(zip_bytes: bytes) -> Tuple[List[Tuple[str, bytes]], List[str]]:
    """
    在内存中解包 ZIP，返回 (支持的周报文件列表, 跳过的文件名列表)。
    不支持嵌套 ZIP；目录条目、隐藏文件与非周报后缀自动跳过。
    """
    entries: List[Tuple[str, bytes]] = []
    skipped: List[str] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if len(entries) >= ZIP_MAX_ENTRIES:
                skipped.append("…（已达单包最大解析条目数，后续忽略）")
                break
            if info.is_dir():
                continue
            name = _decode_zip_name(info)
            if _is_junk_entry(name):
                continue
            if info.file_size > ZIP_MAX_FILE_SIZE:
                skipped.append(f"{PurePosixPath(name).name}（超过 50MB 限制）")
                continue
            suffix = PurePosixPath(name).suffix.lower()
            if suffix not in SUPPORTED_SUFFIXES:
                skipped.append(f"{PurePosixPath(name).name}（不支持的格式 {suffix or '(无后缀)'}）")
                continue
            try:
                data = zf.read(info)
            except Exception:
                skipped.append(f"{PurePosixPath(name).name}（读取失败）")
                continue
            entries.append((PurePosixPath(name).name, data))

    return entries, skipped
