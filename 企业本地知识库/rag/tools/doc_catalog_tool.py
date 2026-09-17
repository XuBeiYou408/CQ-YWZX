import os
import logging
from langchain.tools import tool
from config import folder_path
from rag.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# ==================== 制度清单与摘要来源 ====================
# 清单本身一律从素材目录**实时枚举**（对齐 kb-tool list_knowledge_documents 的做法），
# 不再维护"收录了哪几篇文档"这类会随入库变化而失真的硬编码全集。
#
# _DOC_SUMMARIES 仅作为**可选人工精炼覆盖层**：对少数重点制度给出更贴合业务的概述；
# 未命中此表的文档（如新入库制度）一律从向量库**实时提取正文开头**作为简介，
# 避免被套上"企业通用业务规章与指导细则"这类与实际内容不符的占位简介。
_DOC_SUMMARIES = {
    "企业员工考勤与休假管理制度": "标准工时/弹性工时制度、打卡要求、迟到早退处理、事假/病假/年假/婚假/产假扣款及审批规则。",
    "企业财务差旅与商务报销细则": "国内/海外差旅标准、飞机/高铁/打车交通标准、住宿与餐饮补贴限额、发票合规及报销流程。",
    "研发规范与数据安全保密条例": "代码托管规范、核心数据与密钥保密、客户数据防泄露、个人设备(BYOD)接入红线、离职脱密期。",
    "新员工入职指引与办公设备申领流程": "入职第一天报到指引、办公工位/门禁卡发放、企业邮箱与内网账号开通、笔记本/台式电脑申领标准。",
    "企业知识产权与专利申请奖励办法": "发明专利、实用新型与软件著作权申请流程、职务发明评定标准、一次性申报与授权奖金激励细则。"
}

_SUMMARY_MAX_CHARS = 120

def _live_summary_index() -> dict:
    """从向量库实时构建 {文件名: 正文开头} 索引，为未收录摘要的文档生成真实简介。
    已入库文档即可取到内容；未入库（解析失败/尚未建索引）则缺席，由调用处如实说明。"""
    index = {}
    try:
        _, docs = get_vector_store()
        for d in docs:
            src = os.path.basename(str(d.metadata.get("source", "")))
            if not src or src in index:
                continue
            text = " ".join((d.page_content or "").split())
            if text:
                index[src] = text[:_SUMMARY_MAX_CHARS]
    except Exception as e:
        logger.warning(f"实时摘要索引构建失败: {e}")
    return index

@tool
def doc_catalog_inspector(category: str = "") -> str:
    """
    探查本地企业知识库收录的全部规章制度文件清单与覆盖业务大纲。
    适用于：用户询问“公司有哪些制度”、“包含哪些规章文档”、“有哪些报销或人事指引”等场景。
    输入：可选的分类关键词（如“人事”、“财务”、“研发”、“全部”），可留空。
    输出：当前系统收录的制度文档列表及简介。
    """
    try:
        if not os.path.exists(folder_path):
            return "【本地制度清单】：当前知识库目录为空，暂未载入任何制度文档。"

        files = [f for f in os.listdir(folder_path) if not f.startswith('.')]
        if not files:
            return "【本地制度清单】：当前知识库目录为空，暂未载入任何制度文档。"

        live_index = _live_summary_index()
        lines = [f"【🏢 本地知识库收录制度全景清单】（共 {len(files)} 份）:"]
        filter_kw = (category or "").strip().lower()
        shown = 0

        for filename in sorted(files):
            base_name, ext = os.path.splitext(filename)
            summary = _DOC_SUMMARIES.get(base_name) or live_index.get(filename)
            if not summary:
                summary = "（已收录但暂无可提取正文，可能是扫描件或尚未建立索引，建议重新上传确认）"

            if filter_kw and filter_kw not in filename.lower() and filter_kw not in summary.lower() and filter_kw != "全部":
                continue

            try:
                size_kb = round(os.path.getsize(os.path.join(folder_path, filename)) / 1024, 1)
            except OSError:
                size_kb = 0.0

            shown += 1
            lines.append(f"{shown}. 《{base_name}》[{ext.lstrip('.').upper()} {size_kb}KB]\n   - 涵盖范畴：{summary}")

        if shown == 0:
            lines.append("未查找到与该分类匹配的特定制度，建议查看完整清单。")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"探查本地制度目录异常: {e}")
        return f"探查制度目录时遇到异常: {str(e)}"
