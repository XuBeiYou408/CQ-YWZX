import re
from typing import Optional, Any
from pydantic import BaseModel, Field

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

def valid_session_id(v: str) -> bool:
    return bool(SESSION_ID_PATTERN.fullmatch(v))

# ==================== 请求结构 ====================
class QueryRequest(BaseModel):
    question: str = Field(..., max_length=2000, description="用户提问内容")
    provider: Optional[str] = Field("cloud", description="模型提供方: cloud 或 local")
    model_name: Optional[str] = Field("deepseek-chat", description="调用的具体模型名称")
    api_key: Optional[str] = Field(None, description="自定义 API 密钥 (可选)")
    api_base: Optional[str] = Field(None, description="自定义 API Base URL (可选)")

# 修复 F：Pydantic v1 / v2 版本双向兼容层
try:
    # ===== pydantic v2 =====
    from pydantic import field_validator as _pv_field_validator

    class AgentQueryRequest(BaseModel):
        question: str = Field(..., max_length=2000, description="用户提问内容")
        session_id: str = Field("default_session", description="会话标识")
        provider: Optional[str] = Field("cloud", description="模型提供方: cloud 或 local")
        model_name: Optional[str] = Field("deepseek-chat", description="调用的具体模型名称")
        api_key: Optional[str] = Field(None, description="自定义 API 密钥 (可选)")
        api_base: Optional[str] = Field(None, description="自定义 API Base URL (可选)")

        @_pv_field_validator("session_id")
        @classmethod
        def _validate_session_id(cls, v: str) -> str:
            if not valid_session_id(v):
                raise ValueError("session_id 仅允许字母、数字、下划线、连字符，长度 1-64")
            return v
except ImportError:
    # ===== pydantic v1 回退 =====
    from pydantic import validator as _pv_validator

    class AgentQueryRequest(BaseModel):
        question: str = Field(..., max_length=2000, description="用户提问内容")
        session_id: str = Field("default_session", description="会话标识")
        provider: Optional[str] = Field("cloud", description="模型提供方: cloud 或 local")
        model_name: Optional[str] = Field("deepseek-chat", description="调用的具体模型名称")
        api_key: Optional[str] = Field(None, description="自定义 API 密钥 (可选)")
        api_base: Optional[str] = Field(None, description="自定义 API Base URL (可选)")

        @_pv_validator("session_id", allow_reuse=True)
        def _validate_session_id(cls, v: str) -> str:
            if not valid_session_id(v):
                raise ValueError("session_id 仅允许字母、数字、下划线、连字符，长度 1-64")
            return v

# ==================== 统一 API 响应模型 ====================
class APIResponse(BaseModel):
    code: int = 200
    message: str = "ok"
    data: Optional[Any] = None
