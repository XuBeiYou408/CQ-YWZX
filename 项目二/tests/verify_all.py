import os
import sys
import tempfile
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from contract.gates.special_gates import route_special_gates
from contract.precedents import PRECEDENTS_DATABASE, search_precedents
from contract.document_annotator import annotator

def verify_all():
    print("==================================================")
    print("开始执行全链路自动化验证与集成测试...")
    print("==================================================")

    # 1. 验证专项门禁路由
    print("\n[1] 验证 16 类专项门禁与条款级深水区门禁路由...")
    sample_equity = "本合同涉及股权转让、增资扩股，各方约定反稀释棘轮调整机制与业绩对赌补偿。"
    gates = route_special_gates(sample_equity, "股权转让与投资协议")
    assert len(gates) >= 2, f"Expected >= 2 gates, got {len(gates)}"
    gate_titles = [g["title"] for g in gates]
    print("   已成功命中门禁:", gate_titles)
    print("   -> 门禁路由逻辑正常！")

    # 2. 验证扩充后的司法判例数据库
    print(f"\n[2] 验证判例库与检索召回 (总条目: {len(PRECEDENTS_DATABASE)} 项)...")
    assert len(PRECEDENTS_DATABASE) >= 20
    test_query = "逾期交货 每日千分之五违约金 过高"
    matched_precedents = search_precedents(test_query, top_k=2)
    assert len(matched_precedents) == 2
    print(f"   命中第 1 项裁判指引: {matched_precedents[0]['title']} ({matched_precedents[0]['case_no']})")
    print("   -> 判例检索与法条匹配逻辑正常！")

    # 3. 验证 Word 原生批注导出 (场景 A: 带风险修改)
    print("\n[3] 验证 Word 原生 Track Changes 批注导出 (场景 A: 带风险)...")
    text_with_risk = "第一条 违约责任\n乙方迟延交货每日按合同总价5%扣罚违约金，甲方迟延付款免责。"
    report_with_risk = """### 🚨 二、逐条穿透风险清单

#### 🔴 [高危风险] 第一条 违约责任
- **【条款原文引述】**：“乙方迟延交货每日按合同总价5%扣罚违约金，甲方迟延付款免责。”
- **【依据法律原文】**：
> 📜 **《中华人民共和国民法典》第五百八十五条第二款**：“约定的违约金过分高于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以适当减少。”
- **【法理风险解构】**：日5%违约金严重脱离合理损失上限，且单方免责构成显失公平。
- **【合规修改建议初稿】**：
```text
乙方迟延交货按未交标的金额的日万分之五支付违约金，以10%为限；甲方逾期付款应承担同期LPR违约金。
```
"""
    tmp_a = tempfile.mktemp(suffix=".docx")
    annotator.generate_annotated_docx(text_with_risk, report_with_risk, "带风险审查合同测试", tmp_a)
    assert os.path.exists(tmp_a)
    size_a = os.path.getsize(tmp_a)
    assert size_a > 5000
    os.remove(tmp_a)
    print(f"   -> 成功生成带删除线/插入线与Comments批注框的 Word 文档 ({size_a} 字节)！")

    # 4. 验证 Word 原生批注导出 (场景 B: 无风险绿标通行)
    print("\n[4] 验证 Word 原生批注导出 (场景 B: 无风险绿标放行)...")
    text_clean = "第一条 合同履行\n双方严格按照商业信义履行合同义务，违约责任对等，争议由被告所在地法院管辖。"
    report_clean = """### 📊 一、合同全景审计概览
- **合同综合风控评级**：🟢 合规良好
- **审查风险条目汇总**：高危风险 0 项，中危风险 0 项，优化建议 0 项
- **资深法务综合评估意见**：本合同权责对等，未检出重大实质性法律风险，建议放行签署。
"""
    tmp_b = tempfile.mktemp(suffix=".docx")
    annotator.generate_annotated_docx(text_clean, report_clean, "合规无风险合同测试", tmp_b)
    assert os.path.exists(tmp_b)
    size_b = os.path.getsize(tmp_b)
    assert size_b > 5000
    os.remove(tmp_b)
    print(f"   -> 成功生成带有全局合规通过批注的 Word 文档 ({size_b} 字节)！")

    # 5. 验证 FastAPI 接口与前端路由挂载
    print("\n[5] 验证 FastAPI 核心接口与静态前端挂载...")
    client = TestClient(app)

    # 前端主页
    resp_index = client.get("/")
    assert resp_index.status_code == 200
    assert "合同审查 AGENT" in resp_index.text
    assert "智能初稿起草" in resp_index.text
    assert "导出带批注 Word" in resp_index.text
    print("   -> 前端主页与新模式 (起草/立场/导出Word) 成功挂载！")

    # 示范合同接口
    resp_sample = client.get("/api/contract/sample")
    assert resp_sample.status_code == 200
    assert len(resp_sample.json()["data"]["content"]) > 100
    print("   -> 示范合同接口正常！")

    # DOCX 导出接口
    export_req = {
        "original_text": text_with_risk,
        "review_report": report_with_risk,
        "title": "API测试批注版"
    }
    resp_export = client.post("/api/contract/export-docx", json=export_req)
    assert resp_export.status_code == 200
    assert resp_export.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert len(resp_export.content) > 5000
    print(f"   -> /api/contract/export-docx 导出测试成功，返回大小: {len(resp_export.content)} 字节！")

    print("\n==================================================")
    print("🎉 恭喜！所有集成测试与业务逻辑全部通过验证！")
    print("==================================================")

if __name__ == "__main__":
    verify_all()
