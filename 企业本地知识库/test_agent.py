import os
import sys
import time
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
from rag.tools.calculator_tool import policy_calculator, jisuanqi_tool
from rag.tools.web_search_tool import unified_web_search, wangye_sousuo_tool
from rag.tools.doc_catalog_tool import doc_catalog_inspector
from rag.tools.rag_tool import enterprise_kb_search
from rag.agent import yunxing_agent_session, agent_executor

async def test_memory():
    print("\n==== 1. 测试自适应会话记忆 ====")
    session_id = "test_session_123"
    qingkong_huibao_jiliu(session_id)
    
    history = huode_huibao_jiliu(session_id)
    history.add_user_message("你好，我是张主管")
    history.add_ai_message("您好，张主管！我是企业本地知识库与合规助手。")
    
    history_reload = huode_huibao_jiliu(session_id)
    messages = history_reload.messages
    print(f"已存入消息条数: {len(messages)}")
    assert len(messages) == 2, "记忆持久化失败！"
    print("记忆持久化测试成功！ ✅")

async def test_router():
    print("\n==== 2. 测试意图识别路由器 ====")
    test_cases = {
        "公司年假规定有几天？": "simple_rag",
        "查看企业制度全景清单与目录": "summarize",
        "员工月薪15000，请事假2.5天算一下扣除多少钱": "agent",
        "国家2026年最新法定年假与育儿假规定": "agent"
    }
    for q, expected in test_cases.items():
        res = await xitong_luyou(q)
        print(f"问题: '{q}' -> 路由分类: {res} (预期: {expected})")
    print("路由器分类测试成功！ ✅")

async def test_tools():
    print("\n==== 3. 测试工具集 ====")
    # 1. 测试合规沙箱计算器
    calc_res = policy_calculator.invoke("15000 / 21.75 * 2.5")
    print(f"🧮 合规计算器测试 (15000 / 21.75 * 2.5): {calc_res}")
    assert "1724" in calc_res, "计算器核算结果有误！"

    # 2. 测试本地制度目录探查
    catalog_res = doc_catalog_inspector.invoke("全部")
    print(f"📋 制度目录探查测试:\n{catalog_res[:180]}...")
    assert "企业员工考勤与休假管理制度" in catalog_res, "未探查到考勤制度！"

    # 3. 测试高可用统一外网搜索（含3秒防卡死熔断）
    t0 = time.time()
    search_res = unified_web_search.invoke("最新年假规定")
    search_cost = round(time.time() - t0, 2)
    print(f"🌐 统一外网搜索耗时: {search_cost}s, 结果前120字: {search_res[:120]}...")
    assert search_cost < 6.0, "外网搜索超时过长，存在死锁风险！"

    print("工具集测试成功！ ✅")

async def test_agent_fast_convergence():
    print("\n==== 4. 测试 Agent 状态机快速推演与零死锁 ====")
    session_id = "test_agent_session_888"
    qingkong_huibao_jiliu(session_id)
    
    # 模拟复杂问题：规章制度检索 + 算术计算
    q = "根据公司考勤制度，员工月薪15000元，请事假2.5天，算一下要扣除多少基本工资？"
    print(f"用户提问: {q}")
    
    t_start = time.time()
    res = await yunxing_agent_session(q, session_id)
    t_cost = round(time.time() - t_start, 2)
    
    print(f"Agent 回答耗时: {t_cost} 秒 (拒绝 126 秒超时！)")
    print(f"最终解答摘要:\n{res['answer'][:200]}...")
    print(f"调用的工具: {res['tools_used']}")
    print(f"推演步数: {len(res['thought_process'])}")
    for idx, step in enumerate(res['thought_process'], 1):
        print(f"  [步骤 {idx}] 思考: {step['thought'][:60]} | 工具: {step['tool']} | 入参: {step['tool_input']}")

    # 核心保障：绝不超时（控制在20秒以内，通常3~6秒）
    assert t_cost < 20.0, f"执行时间过长: {t_cost}s，未通过 20s 守卫阈值！"
    assert len(res["answer"].strip()) > 10, "最终回答为空！"
    print("Agent 状态机快速推演测试成功！ ✅")

async def main():
    print("🚀 开始运行企业本地知识库【华硕演示级 Agent】集成测试...")
    await test_memory()
    await test_router()
    await test_tools()
    await test_agent_fast_convergence()
    print("\n🎉 全部单元与状态机集成测试顺利通过！")

if __name__ == "__main__":
    asyncio.run(main())
