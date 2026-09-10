import os
import sys
import asyncio
from dotenv import load_dotenv

# 使用 reconfigure 官方安全方法设置编码，防止重构标准流导致 descriptor 被关闭或崩溃！
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# 将当前目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from rag.memory import huode_huibao_jiliu, qingkong_huibao_jiliu
from rag.router import xitong_luyou
from rag.tools.calculator_tool import jisuanqi_tool
from rag.tools.web_search_tool import wangye_sousuo_tool
from rag.agent import yunxing_agent_session

async def test_memory():
    print("\n==== 1. 测试自适应会话记忆 ====")
    session_id = "test_session_123"
    # 清空可能存在的旧数据
    qingkong_huibao_jiliu(session_id)
    
    history = huode_huibao_jiliu(session_id)
    print(f"当前历史后端: {type(history).__name__}")
    
    history.add_user_message("你好，我是小明")
    history.add_ai_message("你好，小明！很高兴为你服务。")
    
    # 重新加载确认持久化
    history_reload = huode_huibao_jiliu(session_id)
    messages = history_reload.messages
    print(f"已存入消息条数: {len(messages)}")
    for msg in messages:
        print(f" - {msg.type}: {msg.content}")
    assert len(messages) == 2, "记忆持久化失败！"
    print("记忆持久化测试成功！ ✅")

async def test_router():
    print("\n==== 2. 测试意图识别路由器 ====")
    test_cases = {
        "什么是向量数据库？": "simple_rag",
        "帮我生成一份关于Python编程的核心总结与大纲": "summarize",
        "计算 (1024 * 512) / 8 结果是多少": "agent"
    }
    for q, expected in test_cases.items():
        res = await xitong_luyou(q)
        print(f"问题: '{q}' -> 路由分类: {res} (预期: {expected})")

async def test_tools():
    print("\n==== 3. 测试工具集 ====")
    # 测试计算器
    calc_res = jisuanqi_tool.invoke("2**10 + 24")
    print(f"计算器测试 (2**10 + 24): {calc_res}")
    
    # 测试网页搜索 (支持 Firecrawl 驱动)
    search_res = wangye_sousuo_tool.invoke("Python 3.12 release notes")
    print(f"网页搜索测试 (Python 3.12 release notes): {search_res[:150]}...")

async def test_agent():
    print("\n==== 4. 测试 Agent 思考与多轮对话 ====")
    session_id = "test_agent_session_999"
    qingkong_huibao_jiliu(session_id)
    
    # 问题 1：复杂推理 + 计算
    q1 = "如果在知识库中搜索关于'BGE模型'的参数计算，并计算 1024 * 1024 * 4 的值是多少？"
    print(f"用户: {q1}")
    res1 = await yunxing_agent_session(q1, session_id)
    print(f"Agent 回答: {res1['answer']}")
    print(f"调用过的工具: {res1['tools_used']}")
    print(f"思考过程步数: {len(res1['thought_process'])}")
    for idx, step in enumerate(res1['thought_process'], 1):
        print(f"  步骤 {idx} - 思考: {step['thought'][:60]}... -> 调用工具: {step['tool']} -> 参数: {step['tool_input']}")
        
    # 问题 2：多轮对话记忆测试（确认是否记得我的名字）
    history = huode_huibao_jiliu(session_id)
    history.add_user_message("记住，我的名字叫小华，是一个大模型开发工程师。")
    history.add_ai_message("好的，小华，我已经记住了您的名字和职业。")
    
    q2 = "我刚才说我的名字叫什么来着？"
    print(f"\n用户: {q2}")
    res2 = await yunxing_agent_session(q2, session_id)
    print(f"Agent 回答: {res2['answer']}")
    assert "小华" in res2['answer'], "多轮对话记忆提取失败！"
    print("多轮对话记忆测试成功！ ✅")

async def main():
    print("🚀 开始运行 Agent 核心单元集成测试...")
    await test_memory()
    await test_router()
    await test_tools()
    await test_agent()
    print("\n🎉 所有核心测试已通过！")

if __name__ == "__main__":
    asyncio.run(main())
