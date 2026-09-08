"""
智审 (Doc-Agent) - Word 原生审阅批注与修订导出引擎
利用 python-docx 建立标准版式文档，通过 ooxml_lite 注入原生 Track Changes (删除线/插入线) 与 Comments 批注
"""
import os
import re
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional

import docx
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

from contract.ooxml_lite import unpack_docx, pack_docx, LiteDocument, W_NS, _node_text, _now_iso

CLR_TITLE = RGBColor(0x1F, 0x38, 0x64)   # 深蓝商务标题
FONT_HEADING = "黑体"
FONT_BODY = "仿宋"

class DocumentAnnotator:
    """合同批注与修订 Word 导出生成器"""

    def __init__(self, author: str = "智审法务 Agent", initials: str = "DocAgent"):
        self.author = author
        self.initials = initials

    def parse_risks_from_report(self, review_report: str) -> List[Dict[str, Any]]:
        """从 Markdown 审查报告中抽取结构化风险条目"""
        if not review_report:
            return []

        risks = []
        cards = re.split(r'####\s*[🔴🟡🟢]?', review_report)

        for card in cards[1:]:
            level = "中危"
            if "🔴" in card or "高危" in card:
                level = "高危"
            elif "🟡" in card or "中危" in card:
                level = "中危"
            elif "🟢" in card or "建议" in card or "优化" in card:
                level = "优化建议"

            orig_m = re.search(r'【条款原文引述】[\s\S]*?[“"\'「]([\s\S]*?)[”"\'」]', card)
            statute_m = re.search(r'【依据法律原文】[\s\S]*?📜\s*([^：:\n]+)[：:\s]*[“"\'「]([\s\S]*?)[”"\'」]', card)
            reason_m = re.search(r'【法理风险解构】[\s\S]*?([^\n#]+)', card)
            sugg_m = re.search(r'【合规修改建议初稿】[\s\S]*?```(?:text)?\s*([\s\S]*?)\s*```', card)

            orig_clause = orig_m.group(1).strip() if orig_m else ""
            statute_ref = f"{statute_m.group(1)}: {statute_m.group(2)}" if statute_m else ""
            reason = reason_m.group(1).strip() if reason_m else ""
            sugg_clause = sugg_m.group(1).strip() if sugg_m else ""

            if orig_clause:
                risks.append({
                    "level": level,
                    "orig_clause": orig_clause,
                    "statute_ref": statute_ref,
                    "reason": reason,
                    "sugg_clause": sugg_clause
                })

        return risks

    def create_base_docx(self, title: str, text: str, output_docx_path: str) -> None:
        """使用 python-docx 建立干净的标准版式 Word 文档"""
        doc = Document()

        # 设置紧凑正式版式边距
        for sec in doc.sections:
            sec.top_margin = Cm(2.5)
            sec.bottom_margin = Cm(2.5)
            sec.left_margin = Cm(2.8)
            sec.right_margin = Cm(2.8)

        # 标题
        h = doc.add_heading(level=1)
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_h = h.add_run(title or "合同审查审阅初稿")
        run_h.font.name = FONT_HEADING
        run_h.font.size = Pt(18)
        run_h.font.bold = True
        run_h.font.color.rgb = CLR_TITLE

        doc.add_paragraph()  # 空行

        # 正文段落
        paragraphs = text.split("\n")
        for p_text in paragraphs:
            pt = p_text.strip()
            if not pt:
                continue
            p = doc.add_paragraph()
            p.paragraph_format.line_spacing = 1.25
            p.paragraph_format.space_after = Pt(4)

            # 判断是否为各级小标题
            is_clause_title = bool(re.match(r'^(第[一二三四五六七八九十百]+条|条[一二三四五六七八九十百]+|[\d\.]+)', pt))

            r = p.add_run(pt)
            r.font.name = FONT_HEADING if is_clause_title else FONT_BODY
            r.font.size = Pt(12) if is_clause_title else Pt(11)
            r.font.bold = is_clause_title

        doc.save(output_docx_path)

    def generate_annotated_docx(self, original_text: str, review_report: str, title: str, output_path: str) -> str:
        """
        端到端生成带有原生 Word 批注 (Comments) 与修改痕迹 (Track Changes) 的 .docx 文档
        """
        risks = self.parse_risks_from_report(review_report)
        work_dir = Path(tempfile.mkdtemp(prefix="annotated_docx_"))
        base_docx = work_dir / "base.docx"
        unpacked_dir = work_dir / "unpacked"

        try:
            # 1. 建立基础排版文档
            self.create_base_docx(title, original_text, str(base_docx))

            # 2. 解包 docx
            unpack_docx(str(base_docx), str(unpacked_dir))

            # 3. 使用 LiteDocument 注入批注与修订
            lite_doc = LiteDocument(str(unpacked_dir), author=self.author, initials=self.initials)
            editor = lite_doc["word/document.xml"]

            p_nodes = editor.dom.getElementsByTagName("w:p")

            if not risks:
                # 场景 A: 无风险合格合同 -> 在首页第一段留下绿灯合规通过批注
                if len(p_nodes) >= 2:
                    target_p = p_nodes[1]
                    comment_text = "【智审 Agent 合规自检通过】\n全文审查完成：各项主要条款权责平衡、成立生效要素齐备，未识别出重大法律合规缺陷或单方霸王条款，建议推进正常审批与签署。"
                    lite_doc.add_comment(target_p, target_p, comment_text)
            else:
                # 场景 B: 存在风险 -> 遍历风险定位条款并添加批注与修订
                for risk in risks:
                    orig = risk["orig_clause"]
                    sugg = risk["sugg_clause"]
                    statute = risk["statute_ref"]
                    reason = risk["reason"]
                    level = risk["level"]

                    # 寻找匹配的段落
                    matched_p = None
                    # 先找精确或长子串匹配
                    search_keys = [orig[:30], orig[-30:] if len(orig) > 30 else orig]
                    for p in p_nodes:
                        p_txt = _node_text(p)
                        if any(k in p_txt for k in search_keys if len(k) >= 6):
                            matched_p = p
                            break

                    if matched_p:
                        # 1. 注入批注 Comment
                        c_text = f"【{level}提示】\n法理分析：{reason}\n"
                        if statute:
                            c_text += f"法律依据：{statute}\n"
                        if sugg:
                            c_text += f"建议修改为：\n{sugg}"
                        lite_doc.add_comment(matched_p, matched_p, c_text.strip())

                        # 2. 若存在修改建议，则在段落内实现 Track Changes 修订（先删除后插入）
                        if sugg and len(sugg) >= 4:
                            p_txt = _node_text(matched_p)
                            # 生成 Track Changes XML 片段
                            del_ins_xml = (
                                f'<w:del w:id="{lite_doc._next_comment_id()}" w:author="{self.author}" w:date="{_now_iso()}">'
                                f'<w:r><w:delText xml:space="preserve">{orig}</w:delText></w:r>'
                                f'</w:del>'
                                f'<w:ins w:id="{lite_doc._next_comment_id()}" w:author="{self.author}" w:date="{_now_iso()}">'
                                f'<w:r><w:rPr><w:rFonts w:hint="eastAsia" w:eastAsia="{FONT_BODY}"/><w:color w:val="2E74B5"/></w:rPr>'
                                f'<w:t xml:space="preserve">{sugg}</w:t></w:r>'
                                f'</w:ins>'
                            )
                            # 将段落包裹为修订段落
                            try:
                                editor.replace_node(matched_p, f'<w:p xmlns:w="{W_NS}">{del_ins_xml}</w:p>')
                            except Exception:
                                pass  # 若片段替换失败，保留批注

            # 4. 保存 DOM 并重新打包
            lite_doc.save()
            pack_docx(str(unpacked_dir), output_path)
            return output_path

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

annotator = DocumentAnnotator()
