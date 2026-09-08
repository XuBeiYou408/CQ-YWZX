import os
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app

def test_routes():
    client = TestClient(app)
    
    # 1. 健康检查
    res = client.get("/health")
    assert res.status_code == 200
    print("Health check OK:", res.json())

    # 2. 获取判例库列表
    res = client.get("/api/contract/precedents")
    assert res.status_code == 200
    data = res.json()["data"]
    print(f"Precedents count: {len(data)} items")
    assert len(data) >= 20

    # 3. 判例检索
    res = client.post("/api/contract/precedents/search", json={"keyword": "违约金 30% 迟延交付", "top_k": 2})
    assert res.status_code == 200
    search_res = res.json()["data"]
    assert len(search_res) == 2
    print("Precedents search OK, top match:", search_res[0]["title"])

    # 4. Word 批注导出接口测试
    export_payload = {
        "original_text": "第一条 违约责任\n乙方迟延交货每日扣罚5%违约金。\n甲方不承担违约责任。",
        "review_report": "### 🚨 二、逐条穿透风险清单\n\n#### 🔴 [高危风险] 第一条 违约责任\n- **【条款原文引述】**：“乙方迟延交货每日扣罚5%违约金。”\n- **【合规修改建议初稿】**：\n```text\n乙方迟延交货按日万分之五支付违约金。\n```\n",
        "title": "测试合同批注版",
        "format": "docx"
    }
    res = client.post("/api/contract/export-docx", json=export_payload)
    assert res.status_code == 200
    assert len(res.content) > 1000
    print("Export DOCX OK, bytes received:", len(res.content))

if __name__ == "__main__":
    test_routes()
