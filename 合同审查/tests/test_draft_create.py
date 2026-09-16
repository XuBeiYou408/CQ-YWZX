# -*- coding: utf-8 -*-
"""
test_draft_create.py - 合同示范文本起草引擎与接口端到端单测
测试指标：
  1. 7 大主流合同类型示范文本命中与生成覆盖
  2. 极速生成耗时（必须 < 50ms）
  3. 用户真实意向要素（甲乙方/标的/付款/特约防守）精准插槽填充与合规条文化
  4. 立场自适应（偏向甲方 / 偏向乙方 / 中立对等）
  5. FastAPI 接口 /api/contract/draft/create 端到端连通性与数据契约
"""
import os
import sys
import time
import unittest

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contract.draft_templates import render_contract_draft, TEMPLATES, match_template
from contract.engine import engine
from fastapi.testclient import TestClient
from app.main import app


class TestContractDraftTemplates(unittest.TestCase):
    def test_all_seven_templates_coverage(self):
        """验证 7 大合同类型示范文本完整存在"""
        types = [
            "商品货物买卖与采购合同",
            "软件技术开发与外包服务合同",
            "商业房屋与场地租赁合同",
            "劳动用工与人事聘用合同",
            "商业保密与反不正当竞争协议 (NDA)",
            "企业借款与保证担保合同",
            "商务咨询与居间服务合同"
        ]
        for t in types:
            tmpl = match_template(t)
            self.assertIsNotNone(tmpl)
            draft = render_contract_draft(
                contract_type=t,
                party_a="测试甲方科技有限责任公司",
                party_b="测试乙方技术有限责任公司",
                core_subject="测试采购标的及技术指标",
                payment_terms="首期30%，验收后60%，尾款10%",
                special_terms="特约违约金每日万分之五约定",
                client_role="偏向甲方"
            )
            self.assertTrue(len(draft) >= 1000, f"{t} 生成字数不足: {len(draft)}")
            self.assertIn("测试甲方科技有限责任公司", draft)
            self.assertIn("测试乙方技术有限责任公司", draft)
            self.assertIn("测试采购标的及技术指标", draft)

    def test_user_screenshot_scenario_speed_and_content(self):
        """测试用户截图中真实输入的要素，验证毫秒级生成与内容准确性"""
        start = time.time()
        draft = render_contract_draft(
            contract_type="商品买卖与采购合同",
            party_a="计算的话就开始",
            party_b="圣诞节卡号接口对接",
            core_subject="是否考虑实际的罚款联合反恐拉风",
            payment_terms="签订合同后付30%定金，交货初验后付60%，质保期满1年付10%尾款",
            special_terms="双方违约金按日万分之五约定，上限不超过总价10%，争议由甲方所在地法院管辖。",
            client_role="偏向甲方 (采购/委托方)"
        )
        elapsed_ms = (time.time() - start) * 1000
        print(f"\n  -> 用户截图用例起草耗时: {elapsed_ms:.2f} ms，生成字数: {len(draft)} 字")

        # 耗时必须在 50ms 以内（极速秒级按范文出稿）
        self.assertLess(elapsed_ms, 50.0, "范文起草耗时超过50ms")
        self.assertTrue(len(draft) >= 1500, "起草正文字数过短")

        # 要素核验
        self.assertIn("计算的话就开始", draft)
        self.assertIn("圣诞节卡号接口对接", draft)
        self.assertIn("是否考虑实际的罚款联合反恐拉风", draft)
        self.assertIn("签订合同后付30%定金", draft)
        self.assertIn("日万分之五", draft)
        self.assertIn("不超过总价10%", draft)
        self.assertIn("甲方所在地", draft)

    def test_stance_adaptation(self):
        """测试立场自适应分支逻辑"""
        draft_a = render_contract_draft(
            contract_type="买卖合同",
            party_a="甲方公司", party_b="乙方公司", core_subject="设备", client_role="偏向甲方"
        )
        self.assertIn("守约偏向", draft_a)

        draft_b = render_contract_draft(
            contract_type="买卖合同",
            party_a="甲方公司", party_b="乙方公司", core_subject="设备", client_role="偏向乙方"
        )
        self.assertIn("供方偏向", draft_b)

    def test_api_endpoint_draft_create(self):
        """测试 FastAPI /api/contract/draft/create 端到端响应"""
        client = TestClient(app)
        payload = {
            "contract_type": "商品买卖与采购合同",
            "party_a": "计算的话就开始",
            "party_b": "圣诞节卡号接口对接",
            "core_subject": "是否考虑实际的罚款联合反恐拉风",
            "payment_terms": "签订合同后付30%定金，交货初验后付60%，质保期满1年付10%尾款",
            "special_terms": "双方违约金按日万分之五约定，上限不超过总价10%，争议由甲方所在地法院管辖。",
            "client_role": "偏向甲方 (采购/委托方)"
        }
        start = time.time()
        resp = client.post("/api/contract/draft/create", json=payload)
        elapsed_ms = (time.time() - start) * 1000
        print(f"  -> FastAPI 接口响应耗时: {elapsed_ms:.2f} ms")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 200)
        self.assertIn("draft_text", data["data"])
        draft_text = data["data"]["draft_text"]
        self.assertIn("计算的话就开始", draft_text)
        self.assertIn("圣诞节卡号接口对接", draft_text)


if __name__ == "__main__":
    unittest.main()
