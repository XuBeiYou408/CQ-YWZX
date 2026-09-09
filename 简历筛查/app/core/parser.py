"""
简历文档解析模块
支持 PDF (PyMuPDF) / Word (python-docx) / TXT / MD
"""
import re
from pathlib import Path


def extract_text_from_pdf(file_bytes: bytes) -> str:
    import pymupdf
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(pages)


def extract_text_from_docx(file_bytes: bytes) -> str:
    import io
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(para.text for para in doc.paragraphs)


def extract_text_from_bytes(filename: str, file_bytes: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text = extract_text_from_pdf(file_bytes)
    elif suffix == ".docx":
        text = extract_text_from_docx(file_bytes)
    elif suffix in (".txt", ".md", ".doc"):
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("gbk", errors="replace")
    else:
        raise ValueError(f"不支持的文件格式: {suffix}，请上传 PDF / Word / TXT / MD")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
