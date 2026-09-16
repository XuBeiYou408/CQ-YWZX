import os
import logging
from langchain.tools import tool
from config import folder_path

logger = logging.getLogger(__name__)

# 预置制度文档核心业务领域摘要索引
_DOC_SUMMARIES = {
    "企业员工考勤与休假管理制度": "标准工时/弹性工时制度、打卡要求、迟到早退处理、事假/病假/年假/婚假/产假扣款及审批规则。",
    "企业财务差旅与商务报销细则": "国内/海外差旅标准、飞机/高铁/打车交通标准、住宿与餐饮补贴限额、发票合规及报销流程。",
    "研发规范与数据安全保密条例": "代码托管规范、核心数据与密钥保密、客户数据防泄露、个人设备(BYOD)接入红线、离职脱密期。",
    "新员工入职指引与办公设备申领流程": "入职第一天报到指引、办公工位/门禁卡发放、企业邮箱与内网账号开通、笔记本/台式电脑申领标准。",
    "企业知识产权与专利申请奖励办法": "发明专利、实用新型与软件著作权申请流程、职务发明评定标准、一次性申报与授权奖金激励细则。"
}

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

        lines = ["【🏢 本地知识库收录制度全景清单】:"]
        filter_kw = (category or "").strip().lower()

        for idx, filename in enumerate(sorted(files), start=1):
            base_name, _ = os.path.splitext(filename)
            summary = _DOC_SUMMARIES.get(base_name, "企业通用业务规章与指导细则。")
            
            if filter_kw and filter_kw not in filename.lower() and filter_kw not in summary.lower() and filter_kw != "全部":
                continue
                
            lines.append(f"{idx}. 《{base_name}》\n   - 涵盖范畴：{summary}")

        if len(lines) == 1:
            lines.append("未查找到与该分类匹配的特定制度，建议查看完整清单。")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"探查本地制度目录异常: {e}")
        return f"探查制度目录时遇到异常: {str(e)}"
