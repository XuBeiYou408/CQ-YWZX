"""
智审 (Doc-Agent) - LM Studio 本地连通性与流式吐字测试
"""
import asyncio
import sys
import time
from openai import AsyncOpenAI

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

async def test_lmstudio_connection():
    print(">> 开始检测 LM Studio (http://127.0.0.1:1234/v1) ...")
    client = AsyncOpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio")
    
    # 1. 检测模型列表
    models = await client.models.list()
    print(f"✅ 模型发现成功，当前在线模型数: {len(models.data)}")
    for m in models.data:
        print(f"   - 模型 ID: {m.id}")
        
    # 2. 测试流式调用（无模型列表时回退到项目当前固定使用的审查模型）
    from config import config as _cfg
    target_model = models.data[0].id if models.data else (_cfg.AGENT_MODEL or _cfg.DEFAULT_MODEL)
    print(f">> 正在对模型 [{target_model}] 发起法务打招呼流式推理测试...")
    start_t = time.time()
    response = await client.chat.completions.create(
        model=target_model,
        messages=[
            {"role": "system", "content": "你是一名企业资深法务专家。"},
            {"role": "user", "content": "请用一句话告诉我，我国民法典规定违约金超过造成损失的百分之多少通常被认定为过分高于？"}
        ],
        temperature=0.1,
        stream=True
    )
    
    tokens = []
    async for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            token = chunk.choices[0].delta.content
            tokens.append(token)
            print(token, end="", flush=True)
    print()
    cost = round(time.time() - start_t, 2)
    tok_count = len(tokens)
    speed = round(tok_count / cost, 1) if cost > 0 else 0
    print(f"✅ 流式调用成功！耗时: {cost}s, 估算速率: {speed} tok/s")

if __name__ == "__main__":
    asyncio.run(test_lmstudio_connection())
