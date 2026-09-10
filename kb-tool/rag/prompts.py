from langchain_core.prompts import ChatPromptTemplate

# ==================== 定义查询重写（Rewrite）提示词 ====================
rewrite_prompt = ChatPromptTemplate([
    ("system",
     "你是一个针对技术文档库的查询扩展助手。\n"
     "请基于用户问题，生成 3 个不同角度或语言的检索问题。\n"
     "要求：\n"
     "1. 保持语义高度相关。\n"
     "2. **中英双语扩展**：对于包含英文技术术语、代码概念或可能对应英文技术文档（如LangChain, Matplotlib, JSON, PyTorch等）的查询，生成的 3 个问题中必须包含 1-2 个针对性的英文检索词或检索短句（包括代码关键字或配置项，如 `langchain.debug = True` 或 `verbose=True`），以确保能够匹配英文原版文档。\n"
     "3. 每个检索问题用换行分隔，不要包含序号，不要解释。"),
    ("user", "{question}")
])

# ==================== LLM的提示词工厂 ====================
def huode_llm_prompt(provider: str = "cloud", model_name: str = "deepseek-chat"):
    prov_label = "本地部署" if (provider or "").lower() == "local" else "云端 API"
    m_name = model_name or "deepseek-chat"
    
    sys_prompt = (
        f"你是一个全能的企业级 AI 技术导师。\n"
        f"【系统运行状态】：当前后端大语言模型运行在 [{prov_label}] 模式，调用模型标识为 [{m_name}]。\n\n"
        f"回答指导原则：\n"
        f"1. 优先结合下方【参考资料】中检索到的知识库内容解答。\n"
        f"2. 若【参考资料】为空、未直接覆盖提问、或者用户提问属于系统能力/模型版本/通用技术/日常问候，请结合系统运行状态与你自身强大的通用知识库直接精准回答，禁止机械回答未找到！\n"
        f"3. 请直接给出核心结论与要点清单，文字精炼，条理分明，杜绝冗余重复废话。\n\n"
        f"【参考资料】:\n{{context}}"
    )
    return ChatPromptTemplate([
        ('system', sys_prompt),
        ('user', '{input}')
    ])

llm_prompt = huode_llm_prompt("cloud", "deepseek-chat")
