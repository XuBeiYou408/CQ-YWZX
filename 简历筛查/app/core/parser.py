"""
简历文档解析模块
支持 PDF (PyMuPDF) / Word (python-docx) / TXT / MD
"""
import re
from pathlib import Path


def extract_text_from_pdf(file_bytes: bytes) -> str:
    import pymupdf
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"PDF 文件无法打开（{e}），请确认文件未损坏或未加密。")
    try:
        pages = [page.get_text() for page in doc]
    finally:
        doc.close()
    return "\n".join(pages)


def extract_text_from_docx(file_bytes: bytes) -> str:
    import io
    from docx import Document
    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as e:
        raise ValueError(
            f"Word 文档解析失败（{e}）。若这是老版 .doc 文件，请用 Word 另存为 .docx 后重试。"
        )
    return "\n".join(para.text for para in doc.paragraphs)


#: 老版 Word(.doc) 二进制复合文档的魔术字头，无法按纯文本解码
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def extract_text_from_bytes(filename: str, file_bytes: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text = extract_text_from_pdf(file_bytes)
    elif suffix == ".docx":
        text = extract_text_from_docx(file_bytes)
    elif suffix in (".txt", ".md", ".doc"):
        if file_bytes[:8] == _OLE_MAGIC:
            raise ValueError(
                "检测到老版 Word(.doc) 二进制格式，暂不支持直接解析，请用 Word 另存为 .docx（或导出 PDF）后重试。"
            )
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("gbk", errors="replace")
    else:
        raise ValueError(f"不支持的文件格式: {suffix}，请上传 PDF / Word / TXT / MD")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError(
            "未能从该文件中提取到任何文字（可能是扫描件、纯图片简历或空文件），请上传含文字层的 PDF / Word 文件。"
        )
    return text
