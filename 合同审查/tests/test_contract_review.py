"""
智审 (Doc-Agent) - 离线合同审查与判例匹配端到端自动化测试
"""
import asyncio
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 确保父路径导入正常
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sample_contract import SAMPLE_CONTRACT_TEXT
from contract.precedents import search_precedents
from contract.engine import engine

async def test_review_pipeline():
    print(">> 开始测试离线判例匹配引擎...")
    precedents = search_precedents(SAMPLE_CONTRACT_TEXT)
    assert len(precedents) > 0, "判例匹配库不应为空"
    print(f"✅ 成功匹配 {len(precedents)} 条判例:")
    for p in precedents:
        print(f"   * [{p['case_no']}] {p['title']}")
    assert any("违约金" in p['keywords'] for p in precedents), "必须命中违约金司法裁判规则"

    print("\n>> 开始测试端到端流式审查引擎 (Qwen2.5)...")
    content_chunks = []
    # 传入前800字符进行快速功能验证
    async for frame in engine.stream_review(
        contract_text=SAMPLE_CONTRACT_TEXT[:800],
        contract_type="软件技术开发与外包采购合同"
    ):
        if frame.get("type") in ("content", "thought"):
            chunk = frame.get("delta", "")
            content_chunks.append(chunk)
            print(chunk, end="", flush=True)
            if len(content_chunks) >= 20: # 收到足够的流式 token 后即可验证通过
                break

    assert len(content_chunks) > 0, "审查输出不应为空"
    print("\n\n✅ 端到端流式审查测试圆满通过！")

if __name__ == "__main__":
    asyncio.run(test_review_pipeline())
