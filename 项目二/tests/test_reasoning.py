import urllib.request
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

payload = {
    "model": "qwen3.8-27b",
    "messages": [
        {"role": "system", "content": "你是一个合同审查助手。请直接输出分析结果，绝对不要思考，禁止输出任何思维链。"},
        {"role": "user", "content": "请审查这句话是否有违约金过高风险：乙方迟延交货每日按合同总价5%扣罚违约金。"}
    ],
    "max_tokens": 500
}

req = urllib.request.Request(
    "http://127.0.0.1:1234/v1/chat/completions",
    headers={"Content-Type": "application/json"},
    data=json.dumps(payload).encode("utf-8")
)

with urllib.request.urlopen(req, timeout=40) as r:
    data = json.loads(r.read().decode("utf-8"))
    msg = data["choices"][0]["message"]
    print("FINISH_REASON:", data["choices"][0]["finish_reason"])
    print("CONTENT_LEN:", len(msg.get("content") or ""))
    print("REASONING_LEN:", len(msg.get("reasoning_content") or ""))
    print("CONTENT:\n", msg.get("content"))
