import os
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from contract.document_annotator import annotator

def test_annotator():
    title = '测试技术开发采购合同'
    text = '''第一条 双方主体与合作目的
甲方：测试科技股份有限公司
乙方：外包开发服务中心

第二条 违约责任
如乙方迟延交付，每逾期一日应向甲方支付合同总价5%的违约金，直至交付完毕。
甲方迟延付款的，不承担任何迟延履行违约金。

第三条 争议解决
本合同发生争议的，由甲方所在地人民法院管辖。'''

    report = '''### 二、逐条穿透风险清单

#### [高危风险] 第二条 违约责任
- 【条款原文引述】：“如乙方迟延交付，每逾期一日应向甲方支付合同总价5%的违约金，直至交付完毕。”
- 【依据法律原文】：
> 《中华人民共和国民法典》第五百八十五条第二款：“约定的违约金过分高于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以适当减少。”
- 【法理风险解构】：日5%违约金畸高。
- 【合规修改建议初稿】：
```text
如乙方迟延交付，每逾期一日应按未交付标的金额的日万分之五支付违约金。
```
'''

    out = 'test_annotated.docx'
    annotator.generate_annotated_docx(text, report, title, out)
    assert os.path.exists(out)
    size = os.path.getsize(out)
    print(f"✅ DocumentAnnotator 测试通过！生成 docx 大小: {size} 字节")
    os.remove(out)

if __name__ == '__main__':
    test_annotator()
