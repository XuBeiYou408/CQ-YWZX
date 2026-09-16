from langchain_core.prompts import ChatPromptTemplate

# ==================== 定义查询重写（Rewrite）提示词 ====================
rewrite_prompt = ChatPromptTemplate([
    ("system",
     "你是一个针对企业规章与行政制度文档库的查询扩展助手。\n"
     "请基于用户问题，生成 2 个不同表述角度的核心检索提问。\n"
     "要求：\n"
     "1. 保持语义高度聚焦于企业内部规章制度（考勤、休假、差旅报销、数据保密、新员工指引、知识产权等）。\n"
     "2. 提取出精准的名词术语（如：事假扣除、住宿补贴标准、代码保密红线、办公电脑申领）。\n"
     "3. 每个检索问题用换行分隔，不要包含序号，不要附加任何解释说明。"),
    ("user", "{question}")
])

# ==================== LLM的提示词工厂 ====================
def huode_llm_prompt(provider: str = "cloud", model_name: str = "deepseek-chat"):
    prov_label = "本地端侧硬件部署" if (provider or "").lower() == "local" else "云端 API"
    m_name = model_name or "deepseek-chat"
    
    sys_prompt = (
        f"你是一个严谨、高效的企业本地智能知识库与业务合规助手。\n"
        f"【系统运行状态】：当前后端大语言模型运行在 [{prov_label}] 模式，调用模型标识为 [{m_name}]。\n\n"
        f"回答指导原则：\n"
        f"1. 优先严格基于下方【企业本地参考规章】中检索到的制度内容解答。\n"
        f"2. 若涉及员工考勤、差旅报销、研发保密、设备申领等制度事项，请明确标出规章名称（如《企业员工考勤与休假管理制度》）并列出具体条款依据与操作流程。\n"
        f"3. 若【参考资料】未直接覆盖提问、或提问属于外部常识/行业动态，请结合系统运行状态与自身知识库直接精准回答，并客观说明本知识库当前的收录范围。\n"
        f"4. 格式严谨规范，重点内容以加粗或分点呈现，杜绝废话与机械空话。\n\n"
        f"【企业本地参考规章】:\n{{context}}"
    )
    return ChatPromptTemplate([
        ('system', sys_prompt),
        ('user', '{input}')
    ])

llm_prompt = huode_llm_prompt("cloud", "deepseek-chat")
