import re
from typing import Optional, Any, List
from pydantic import BaseModel, Field

class APIResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None

class ContractReviewRequest(BaseModel):
    contract_text: str = Field(..., min_length=10, max_length=100000, description="合同全文或待审文本")
    contract_type: Optional[str] = Field("通用商业民商事经济合同", description="合同类型")
    client_role: Optional[str] = Field("中立合规把关", description="我方代表立场：甲方、乙方、中立合规把关")
    review_stance: Optional[str] = Field("对等平衡", description="审查风格：对等平衡、强势防守、商业促成")
    focus_dimensions: Optional[List[str]] = Field(
        default=["违约金与付款账期", "单方解除权", "专有知识产权归属", "霸王免责与不可抗力", "争议管辖"],
        description="重点关注维度"
    )
    model_name: Optional[str] = Field(None, description="LM Studio 指定模型，留空则自动感知当前加载模型")

class PrecedentSearchRequest(BaseModel):
    keyword: str = Field(..., description="检索关键词或风险类型")
    top_k: int = Field(3, description="返回判例数量")

class ContractExportRequest(BaseModel):
    original_text: str = Field(..., description="原合同文本")
    review_report: str = Field(..., description="审查报告内容")
    title: Optional[str] = Field("合同审查审阅初稿", description="文档标题")
    format: str = Field("docx", description="导出格式: docx, txt, markdown")

class ContractDraftRequest(BaseModel):
    contract_type: str = Field(..., description="要起草的合同类型")
    party_a: str = Field(..., description="甲方主体全称")
    party_b: str = Field(..., description="乙方主体全称")
    core_subject: str = Field(..., description="合作标的与金额标的")
    payment_terms: Optional[str] = Field("按阶段验收付款", description="付款与结算节点")
    special_terms: Optional[str] = Field("", description="特别商业约定或补充要求")
    client_role: Optional[str] = Field("甲方", description="起草立场偏向：甲方、乙方、中立对等")
    model_name: Optional[str] = Field(None, description="指定模型名称")

# ==================== 模型管理 ====================
class ModelSection(BaseModel):
    """本地 / 云端 任一侧的连接参数（未提供的字段保持原值不动）"""
    base_url: Optional[str] = Field(None, description="OpenAI 兼容端点，如 http://127.0.0.1:1234/v1")
    model: Optional[str] = Field(None, description="模型 id；本地留空表示走自动优选")
    api_key: Optional[str] = Field(None, description="API Key（留空字符串表示不改动已存的密钥）")
    preset: Optional[str] = Field(None, description="云端预设标识：deepseek/kimi/qwen/zhipu/custom")

class ModelConfigRequest(BaseModel):
    provider: Optional[str] = Field(None, description="服务类型：local（本地 LM Studio）或 cloud（云端 API）")
    local: Optional[ModelSection] = None
    cloud: Optional[ModelSection] = None

class ModelTestRequest(BaseModel):
    """连通性测试：不传则用当前已保存的生效配置测试"""
    provider: Optional[str] = Field(None, description="local / cloud；留空用当前生效配置")
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    preset: Optional[str] = None
