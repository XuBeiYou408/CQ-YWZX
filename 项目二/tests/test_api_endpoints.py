import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_all_endpoints():
    print(">> 测试 1: GET /health")
    r = client.get('/health')
    assert r.status_code == 200
    print("   [OK]", r.json())

    print(">> 测试 2: GET /api/contract/sample")
    r = client.get('/api/contract/sample')
    assert r.status_code == 200
    d = r.json()['data']
    print(f"   [OK] 标题: {d['title']}, 字数: {d['char_count']}")

    print(">> 测试 3: GET /api/contract/precedents")
    r = client.get('/api/contract/precedents')
    assert r.status_code == 200
    print(f"   [OK] 判例库数量: {len(r.json()['data'])}")

    print(">> 测试 4: GET /api/lmstudio/status")
    r = client.get('/api/lmstudio/status')
    assert r.status_code == 200
    st = r.json()['data']
    print(f"   [OK] 连接状态: {st['connected']}, 当前模型: {st.get('active_model')}")

    print(">> 测试 5: GET / (前端页面)")
    r = client.get('/')
    assert r.status_code == 200
    assert "合同审查 AGENT" in r.text
    print(f"   [OK] 页面加载成功, HTML 字符数: {len(r.text)}")

    print("\n✅ 所有 API 与前端路由测试全部通过！")

if __name__ == "__main__":
    test_all_endpoints()
