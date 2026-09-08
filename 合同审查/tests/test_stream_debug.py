import asyncio
import sys
import time
sys.path.insert(0, ".")
from openai import AsyncOpenAI
from sample_contract import SAMPLE_CONTRACT_TEXT
from contract.prompts import AUDIT_SYSTEM_PROMPT

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from contract.engine import engine

async def test_stream():
    print("Testing engine.stream_review...", flush=True)
    frames = []
    content_chunks = []
    t0 = time.time()
    async for frame in engine.stream_review(SAMPLE_CONTRACT_TEXT[:600], "软件技术开发与外包采购合同"):
        ft = frame.get("type")
        frames.append(ft)
        if ft == "content":
            delta = frame.get("delta", "")
            content_chunks.append(delta)
            print(delta, end="", flush=True)
        elif ft == "status":
            print(f"\n[Status: {frame.get('message')}]", flush=True)
        elif ft == "precedents":
            print(f"\n[Precedents: {len(frame.get('data', []))} matched]", flush=True)
        elif ft == "draft":
            print(f"\n[Draft len: {len(frame.get('data', ''))}, is_perfect: {frame.get('is_perfect')}]", flush=True)
        elif ft == "done":
            print(f"\n[Done: {frame.get('message')}]", flush=True)

    full = "".join(content_chunks)
    print(f"\nCompleted in {time.time()-t0:.2f}s, content len: {len(full)}")
    assert len(full) > 50, "Full report should not be empty!"
    print("ALL CHECKS PASSED!")

if __name__ == "__main__":
    asyncio.run(test_stream())
