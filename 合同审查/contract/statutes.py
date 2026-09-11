"""
智审 (Doc-Agent) - 可检索法条库与引用核验模块
将原先硬编码在卡片文案中的法条抽离为结构化数据库，支撑：
1. Agent 行动层 statute_lookup 工具（按关键词检索法条原文）
2. Agent 反思层幻觉核验（报告中引用的条文号/案号必须在库内可追溯）
"""

from typing import Any, Dict, List, Optional, Set
import re

from contract.precedents import PRECEDENTS_DATABASE


# ---------------------------------------------------------------------------
# 法条数据库（article_id 为纯数字字符串，如 "585" 代表民法典第五百八十五条）
# text_scale: "原文" 表示逐字条文；"要旨" 表示裁判尺度摘要（用于检索参考）
# ---------------------------------------------------------------------------
STATUTES_DATABASE: List[Dict[str, Any]] = [
    {
        "article_id": "585", "law": "中华人民共和国民法典", "article": "第五百八十五条",
        "title": "违约金调整规则（过高酌减 / 过低增加）", "text_scale": "原文",
        "text": "当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金，也可以约定因违约产生的损失赔偿额的计算方法。约定的违约金低于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以增加；约定的违约金过分高于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以适当减少。当事人就迟延履行约定违约金的，违约方支付违约金后，还应当履行债务。",
        "keywords": ["违约金", "过高", "酌减", "惩罚性", "迟延履行", "损失", "赔偿"],
        "related_cases": ["(2022)最高法民终184号"],
    },
    {
        "article_id": "496", "law": "中华人民共和国民法典", "article": "第四百九十六条",
        "title": "格式条款的定义与提示说明义务", "text_scale": "原文",
        "text": "格式条款是当事人为了重复使用而预先拟定，并在订立合同时未与对方协商的条款。采用格式条款订立合同的，提供格式条款的一方应当遵循公平原则确定当事人之间的权利和义务，并采取合理的方式提示对方注意免除或者减轻其责任等与对方有重大利害关系的条款，按照对方的要求，对该条款予以说明。提供格式条款的一方未履行提示或者说明义务，致使对方没有注意或者理解与其有重大利害关系的条款的，对方可以主张该条款不成为合同的内容。",
        "keywords": ["格式条款", "提示义务", "说明义务", "霸王条款", "预先拟定"],
        "related_cases": ["(2023)最高法民再441号"],
    },
    {
        "article_id": "497", "law": "中华人民共和国民法典", "article": "第四百九十七条",
        "title": "格式条款无效情形", "text_scale": "原文",
        "text": "有下列情形之一的，该格式条款无效：（一）具有本法第一编第六章第三节和本法第五百零六条规定的无效情形；（二）提供格式条款一方不合理地免除或者减轻其责任、加重对方责任、限制对方主要权利；（三）提供格式条款一方排除对方主要权利。",
        "keywords": ["格式条款", "无效", "免除责任", "加重责任", "排除权利", "免责"],
        "related_cases": ["(2023)最高法民再441号"],
    },
    {
        "article_id": "563", "law": "中华人民共和国民法典", "article": "第五百六十三条",
        "title": "合同的法定解除情形", "text_scale": "原文",
        "text": "有下列情形之一的，当事人可以解除合同：（一）因不可抗力致使不能实现合同目的；（二）在履行期限届满前，当事人一方明确表示或者以自己的行为表明不履行主要债务；（三）当事人一方迟延履行主要债务，经催告后在合理期限内仍未履行；（四）当事人一方迟延履行债务或者有其他违约行为致使不能实现合同目的；（五）法律规定的其他情形。以持续履行的债务为内容的不定期合同，当事人可以随时解除合同，但是应当在合理期限之前通知对方。",
        "keywords": ["解除合同", "法定解除", "单方解除", "任意解除", "催告"],
        "related_cases": ["(2020)最高法民终115号"],
    },
    {
        "article_id": "566", "law": "中华人民共和国民法典", "article": "第五百六十六条",
        "title": "合同解除的法律后果", "text_scale": "原文",
        "text": "合同解除后，尚未履行的，终止履行；已经履行的，根据履行情况和合同性质，当事人可以请求恢复原状或者采取其他补救措施，并有权请求赔偿损失。合同因违约解除的，解除权人可以请求违约方承担违约责任，但是当事人另有约定的除外。",
        "keywords": ["解除后果", "恢复原状", "赔偿损失", "清算", "补救措施"],
        "related_cases": ["(2020)最高法民终115号"],
    },
    {
        "article_id": "511", "law": "中华人民共和国民法典", "article": "第五百一十一条",
        "title": "约定不明时的履行规则", "text_scale": "原文",
        "text": "当事人就有关合同内容约定不明确，依据前条规定仍不能确定的，适用下列规定：（一）质量要求不明确的，按照强制性国家标准履行；没有强制性国家标准的，按照推荐性国家标准履行；没有推荐性国家标准的，按照行业标准履行；没有国家标准、行业标准的，按照通常标准或者符合合同目的的特定标准履行。（二）价款或者报酬不明确的，按照订立合同时履行地的市场价格履行……（四）履行期限不明确的，债务人可以随时履行，债权人也可以随时请求履行，但是应当给对方必要的准备时间。",
        "keywords": ["约定不明", "履行期限", "必要准备时间", "验收期限", "质量标准"],
        "related_cases": ["(2019)最高法民终732号"],
    },
    {
        "article_id": "628", "law": "中华人民共和国民法典", "article": "第六百二十八条",
        "title": "买受人支付价款的时间", "text_scale": "原文",
        "text": "买受人应当按照约定的数额和支付方式支付价款。对价款的数额和支付方式没有约定或者约定不明确的，适用本法第五百一十条、第五百一十一条第二项和第五项的规定。",
        "keywords": ["付款时间", "价款", "结算", "支付方式"],
        "related_cases": ["(2019)最高法民终732号"],
    },
    {
        "article_id": "586", "law": "中华人民共和国民法典", "article": "第五百八十六条",
        "title": "定金合同与定金数额上限", "text_scale": "原文",
        "text": "当事人可以约定一方向对方给付定金作为债权的担保。定金合同自实际交付定金时成立。定金的数额由当事人约定；但是，不得超过主合同标的额的百分之二十，超过部分不产生定金的效力。实际交付的定金数额多于或者少于约定数额的，视为变更约定的定金数额。",
        "keywords": ["定金", "百分之二十", "担保", "20%"],
        "related_cases": ["(2021)最高法民再289号"],
    },
    {
        "article_id": "588", "law": "中华人民共和国民法典", "article": "第五百八十八条",
        "title": "违约金与定金的选择适用", "text_scale": "原文",
        "text": "当事人既约定违约金，又约定定金的，一方违约时，对方可以选择适用违约金或者定金条款。定金不足以弥补一方违约造成的损失的，对方可以请求赔偿超过定金数额的损失。",
        "keywords": ["定金", "违约金", "并用", "选择适用"],
        "related_cases": ["(2021)最高法民再289号"],
    },
    {
        "article_id": "621", "law": "中华人民共和国民法典", "article": "第六百二十一条",
        "title": "买受人检验与异议期限", "text_scale": "原文",
        "text": "当事人约定检验期限的，买受人应当在检验期限内将标的物的数量或者质量不符合约定的情形通知出卖人。买受人怠于通知的，视为标的物的数量或者质量符合约定。当事人没有约定检验期限的，买受人应当在发现或者应当发现标的物的数量或者质量不符合约定的合理期限内通知出卖人……",
        "keywords": ["检验期", "异议期", "验收", "质量异议", "隐蔽瑕疵"],
        "related_cases": ["(2022)最高法民终312号"],
    },
    {
        "article_id": "620", "law": "中华人民共和国民法典", "article": "第六百二十条",
        "title": "买受人的及时检验义务", "text_scale": "原文",
        "text": "买受人收到标的物时应当在约定的检验期限内检验。没有约定检验期限的，应当及时检验。",
        "keywords": ["检验", "验收", "收货"],
        "related_cases": ["(2022)最高法民终312号"],
    },
    {
        "article_id": "705", "law": "中华人民共和国民法典", "article": "第七百零五条",
        "title": "租赁期限的法定上限（20年）", "text_scale": "原文",
        "text": "租赁期限不得超过二十年。超过二十年的，超过部分无效。租赁期限届满，当事人可以续订租赁合同；但是，约定的租赁期限自续订之日起不得超过二十年。",
        "keywords": ["租赁", "二十年", "租期", "续租"],
        "related_cases": ["(2021)最高法民终406号"],
    },
    {
        "article_id": "716", "law": "中华人民共和国民法典", "article": "第七百一十六条",
        "title": "承租人转租规则", "text_scale": "原文",
        "text": "承租人经出租人同意，可以将租赁物转租给第三人。承租人转租的，承租人与出租人之间的租赁合同继续有效；第三人造成租赁物损失的，承租人应当赔偿损失。承租人未经出租人同意转租的，出租人可以解除合同。",
        "keywords": ["转租", "租赁", "分租"],
        "related_cases": ["(2021)最高法民终406号"],
    },
    {
        "article_id": "686", "law": "中华人民共和国民法典", "article": "第六百八十六条",
        "title": "保证方式没有约定或约定不明的推定（一般保证）", "text_scale": "原文",
        "text": "保证的方式包括一般保证和连带责任保证。当事人在保证合同中对保证方式没有约定或者约定不明确的，按照一般保证承担保证责任。",
        "keywords": ["保证", "一般保证", "连带责任", "担保", "保证方式"],
        "related_cases": ["民法典第686条权威释义与判例指导"],
    },
    {
        "article_id": "850", "law": "中华人民共和国民法典", "article": "第八百五十条",
        "title": "技术合同无效情形（非法垄断技术或侵害他人技术成果）", "text_scale": "原文",
        "text": "非法垄断技术或者侵害他人技术成果的技术合同无效。",
        "keywords": ["技术合同", "无效", "知识产权", "技术成果"],
        "related_cases": ["(2021)最高法知民终892号"],
    },
    {
        "article_id": "851", "law": "中华人民共和国民法典", "article": "第八百五十一条",
        "title": "技术开发合同的定义与委托开发形式", "text_scale": "原文",
        "text": "技术开发合同是当事人之间就新技术、新产品、新工艺、新品种或者新材料及其系统的研究开发所订立的合同。技术开发合同包括委托开发合同和合作开发合同。技术开发合同应当采用书面形式。",
        "keywords": ["技术开发", "委托开发", "定制开发", "软件外包"],
        "related_cases": ["(2021)最高法知民终892号"],
    },
    {
        "article_id": "525", "law": "中华人民共和国民法典", "article": "第五百二十五条",
        "title": "同时履行抗辩权", "text_scale": "原文",
        "text": "当事人互负债务，没有先后履行顺序的，应当同时履行。一方在对方履行之前有权拒绝其履行请求。一方在对方履行债务不符合约定时，有权拒绝其相应的履行请求。",
        "keywords": ["同时履行", "抗辩权", "先票后款", "发票"],
        "related_cases": ["(2021)最高法民再355号"],
    },
    {
        "article_id": "526", "law": "中华人民共和国民法典", "article": "第五百二十六条",
        "title": "先履行抗辩权", "text_scale": "原文",
        "text": "当事人互负债务，有先后履行顺序，应当先履行债务一方未履行的，后履行一方有权拒绝其履行请求。先履行一方履行债务不符合约定的，后履行一方有权拒绝其相应的履行请求。",
        "keywords": ["先履行", "抗辩权", "先票后款", "付款条件"],
        "related_cases": ["(2021)最高法民再355号"],
    },
    {
        "article_id": "590", "law": "中华人民共和国民法典", "article": "第五百九十条",
        "title": "不可抗力的免责与通知义务", "text_scale": "原文",
        "text": "当事人一方因不可抗力不能履行合同的，根据不可抗力的影响，部分或者全部免除责任，但是法律另有规定的除外。因不可抗力不能履行合同的，应当及时通知对方，以减轻可能给对方造成的损失，并应当在合理期限内提供证明。当事人迟延履行后发生不可抗力的，不免除其违约责任。",
        "keywords": ["不可抗力", "免责", "通知义务", "证明"],
        "related_cases": ["(2020)最高法民终812号"],
    },
    {
        "article_id": "591", "law": "中华人民共和国民法典", "article": "第五百九十一条",
        "title": "减损义务（防止损失扩大）", "text_scale": "原文",
        "text": "当事人一方违约后，对方应当采取适当措施防止损失的扩大；没有采取适当措施致使损失扩大的，不得就扩大的损失请求赔偿。当事人因防止损失扩大而支出的合理费用，由违约方负担。",
        "keywords": ["减损义务", "损失扩大", "违约"],
        "related_cases": ["(2020)最高法民终812号"],
    },
    {
        "article_id": "965", "law": "中华人民共和国民法典", "article": "第九百六十五条",
        "title": "中介合同中『跳单』的报酬支付义务", "text_scale": "原文",
        "text": "委托人在接受中介人的服务后，利用中介人提供的交易机会或者媒介服务，绕开中介人直接与第三人订立合同的，应当向中介人支付报酬。",
        "keywords": ["中介", "居间", "跳单", "佣金"],
        "related_cases": ["(2021)最高法知民终1102号"],
    },
    {
        "article_id": "933", "law": "中华人民共和国民法典", "article": "第九百三十三条",
        "title": "委托合同的任意解除权与损失赔偿", "text_scale": "原文",
        "text": "委托人或者受托人可以随时解除委托合同。因解除合同造成对方损失的，除不可归责于该当事人的事由外，无偿委托合同的解除方应当赔偿因解除时间不当造成的直接损失，有偿委托合同的解除方应当赔偿对方的直接损失和合同履行后可以获得的利益。",
        "keywords": ["委托合同", "任意解除", "直接损失", "可得利益"],
        "related_cases": ["(2022)最高法民终415号"],
    },
    {
        "article_id": "787", "law": "中华人民共和国民法典", "article": "第七百八十七条",
        "title": "承揽合同定作人任意解除权", "text_scale": "原文",
        "text": "定作人在承揽人完成工作前可以随时解除合同，造成承揽人损失的，应当赔偿损失。",
        "keywords": ["承揽", "定作人", "随时解除", "加工"],
        "related_cases": ["(2020)最高法民终611号"],
    },
    {
        "article_id": "19", "law": "中华人民共和国劳动合同法", "article": "第十九条",
        "title": "试用期的法定上限", "text_scale": "原文",
        "text": "劳动合同期限三个月以上不满一年的，试用期不得超过一个月；劳动合同期限一年以上不满三年的，试用期不得超过二个月；三年以上固定期限和无固定期限的劳动合同，试用期不得超过六个月。同一用人单位与同一劳动者只能约定一次试用期。",
        "keywords": ["试用期", "劳动合同", "上限", "转正"],
        "related_cases": ["最高法指导案例182号"],
    },
    {
        "article_id": "83", "law": "中华人民共和国劳动合同法", "article": "第八十三条",
        "title": "违法约定试用期的赔偿", "text_scale": "原文",
        "text": "用人单位违反本法规定与劳动者约定试用期的，由劳动行政部门责令改正；违法约定的试用期已经履行的，由用人单位以劳动者试用期满月工资为标准，按已经履行的超过法定试用期的期间向劳动者支付赔偿金。",
        "keywords": ["试用期", "违法约定", "赔偿金", "双倍工资"],
        "related_cases": ["最高法指导案例182号"],
    },
    {
        "article_id": "23", "law": "中华人民共和国劳动合同法", "article": "第二十三条",
        "title": "保密义务与竞业限制补偿", "text_scale": "原文",
        "text": "用人单位与劳动者可以在劳动合同中约定保守用人单位的商业秘密和与知识产权相关的保密事项。对负有保密义务的劳动者，用人单位可以在劳动合同或者保密协议中与劳动者约定竞业限制条款，并约定在解除或者终止劳动合同后，在竞业限制期限内按月给予劳动者经济补偿。劳动者违反竞业限制约定的，应当按照约定向用人单位支付违约金。",
        "keywords": ["竞业限制", "保密", "经济补偿", "违约金"],
        "related_cases": ["(2020)最高法民终198号"],
    },
    {
        "article_id": "24", "law": "中华人民共和国劳动合同法", "article": "第二十四条",
        "title": "竞业限制的适用主体与期限", "text_scale": "原文",
        "text": "竞业限制的人员限于用人单位的高级管理人员、高级技术人员和其他负有保密义务的人员。竞业限制的范围、地域、期限由用人单位与劳动者约定，竞业限制的约定不得违反法律、法规的规定。在解除或者终止劳动合同后，前款规定的人员到与本单位生产或者经营同类产品、从事同类业务的有竞争关系的其他用人单位，或者自己开业生产或者经营同类产品、从事同类业务的竞业限制期限，不得超过二年。",
        "keywords": ["竞业限制", "适用主体", "二年", "竞争关系"],
        "related_cases": ["(2020)最高法民终198号"],
    },
    {
        "article_id": "35", "law": "中华人民共和国民事诉讼法", "article": "第三十五条",
        "title": "协议管辖的法定连接点", "text_scale": "原文",
        "text": "合同或者其他财产权益纠纷的当事人可以书面协议选择被告住所地、合同履行地、合同签订地、原告住所地、标的物所在地等与争议有实际联系的地点的人民法院管辖，但不得违反本法对级别管辖和专属管辖的规定。",
        "keywords": ["管辖", "协议管辖", "法院", "争议解决"],
        "related_cases": ["(2020)最高法民辖终88号"],
    },
    {
        "article_id": "16", "law": "中华人民共和国仲裁法", "article": "第十六条",
        "title": "仲裁协议的有效要件", "text_scale": "原文",
        "text": "仲裁协议包括合同中订立的仲裁条款和以其他书面方式在纠纷发生前或者纠纷发生后达成的请求仲裁的协议。仲裁协议应当具有下列内容：（一）请求仲裁的意思表示；（二）仲裁事项；（三）选定的仲裁委员会。",
        "keywords": ["仲裁", "仲裁委员会", "仲裁协议", "争议解决"],
        "related_cases": ["(2020)最高法民辖终88号"],
    },
    {
        "article_id": "9", "law": "中华人民共和国反不正当竞争法", "article": "第九条",
        "title": "商业秘密的构成要件与侵权禁止", "text_scale": "要旨",
        "text": "经营者不得实施下列侵犯商业秘密的行为：（一）以盗窃、贿赂、欺诈、胁迫、电子侵入或者其他不正当手段获取权利人的商业秘密；（二）披露、使用或者允许他人使用以前项手段获取的权利人的商业秘密……本法所称的商业秘密，是指不为公众所知悉、具有商业价值并经权利人采取相应保密措施的技术信息、经营信息等商业信息。",
        "keywords": ["商业秘密", "保密信息", "秘密性", "公知信息"],
        "related_cases": ["(2021)最高法知民终516号"],
    },
]


# ---------------------------------------------------------------------------
# 条文号中文数字 <-> 阿拉伯数字 归一化
# ---------------------------------------------------------------------------
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def chinese_article_to_int(cn: str) -> Optional[int]:
    """将中文数字条文号（如 五百八十五）转为整数 585；解析失败返回 None"""
    cn = cn.replace("第", "").replace("条", "").strip()
    if not cn:
        return None
    if cn.isdigit():
        return int(cn)
    total, num = 0, 0
    for ch in cn:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            if num == 0:
                num = 1
            total += num * unit
            num = 0
        else:
            return None
    total += num
    return total if total > 0 else None


#: 法律名称识别（书名号引用 或 常见法律简称）
_LAW_MENTION_RE = re.compile(
    r"《[^》]{1,40}》"
    r"|中华人民共和国民法典|民法典|劳动法|劳动合同法|民事诉讼法|仲裁法|公司法"
    r"|反不正当竞争法|数据安全法|个人信息保护法|消费者权益保护法|民事诉讼法解释"
)

#: 任意「第X条」形式（含中文数字）
_ANY_ARTICLE_RE = re.compile(r"第\s*([零〇一二三四五六七八九十百千两\d]{1,12})\s*条")


def extract_article_refs(text: str) -> Set[str]:
    """
    抽取文本中引用的**法律条文号**（归一化为阿拉伯数字字符串集合）。

    关键约束：仅当同一句（以。；换行切分）内出现法律名称时，该句中的「第X条」
    才被视为法条引用。否则会误把合同自身的条款号（如「第五条 违约责任」）
    当作法条引用核验，产生大量「未核实」误报。
    """
    refs: Set[str] = set()
    for seg in re.split(r"[。；;\n\r]", text or ""):
        if not _LAW_MENTION_RE.search(seg):
            continue
        for m in _ANY_ARTICLE_RE.finditer(seg):
            val = chinese_article_to_int(m.group(1))
            if val is not None:
                refs.add(str(val))
    return refs


_CASE_REF_RE = re.compile(
    r"[（(]\s*(?:19|20)\d{2}\s*[）)][^，。；、\s（）()]{0,20}?\d+号"
    r"|最高法[^，。；、\s（）()]{0,12}?\d+号"
    r"|指导案例\s*\d+号"
)


def extract_case_refs(text: str) -> List[str]:
    """抽取文本中引用的案号（如 (2022)最高法民终184号 / 最高法指导案例182号）"""
    return _CASE_REF_RE.findall(text or "")


def search_statutes(keyword: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """按关键词检索法条库，返回最相关的条文"""
    if not keyword:
        return []
    kw = keyword.strip().lower()
    text = f" {kw} "
    scored = []
    for st in STATUTES_DATABASE:
        score = 0
        for k in st["keywords"]:
            if k.lower() in kw or kw in k.lower():
                score += 4
        if st["title"] and kw in st["title"].lower():
            score += 5
        if any(k in text for k in st["keywords"]):
            score += 3
        if st["law"] and st["law"] in keyword:
            score += 2
        if score > 0:
            scored.append((score, st))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:top_k]]


def get_statute_by_article_id(article_id: str) -> Optional[Dict[str, Any]]:
    for st in STATUTES_DATABASE:
        if st["article_id"] == str(article_id):
            return st
    return None


def _all_known_case_nos() -> List[str]:
    nos = []
    for p in PRECEDENTS_DATABASE:
        cn = p.get("case_no") or ""
        # case_no 形如 "(2022)最高法民终184号 / 民法典第585条"，拆出案号部分
        for part in cn.split("/"):
            part = part.strip()
            if "号" in part:
                nos.append(part)
        if p.get("id", "").startswith("STATUTE-"):
            pass
    return nos


def verify_citations(text: str) -> Dict[str, Any]:
    """
    幻觉核验：检查文本中引用的条文号与案号是否可在法条库/判例库中追溯。
    未命中不代表一定是幻觉，但必须在报告中标注「未核实」。
    """
    article_refs = extract_article_refs(text)
    known_articles = {st["article_id"] for st in STATUTES_DATABASE}
    articles_ok = sorted(r for r in article_refs if r in known_articles)
    articles_unknown = sorted(r for r in article_refs if r not in known_articles)

    case_refs = extract_case_refs(text)
    known_cases = _all_known_case_nos()
    cases_ok, cases_unknown = [], []
    for ref in case_refs:
        ref_clean = ref.strip()
        # 双向包含匹配：报告引用与库内案号互为子串即视为可追溯
        if any(ref_clean in kc or kc in ref_clean for kc in known_cases):
            cases_ok.append(ref_clean)
        else:
            cases_unknown.append(ref_clean)

    return {
        "articles_verified": articles_ok,
        "articles_unverified": articles_unknown,
        "cases_verified": cases_ok,
        "cases_unverified": cases_unknown,
        "all_verified": (not articles_unknown) and (not cases_unknown),
    }


def format_statute_for_prompt(st: Dict[str, Any]) -> str:
    """将法条条目格式化为可注入 Prompt 的文本块"""
    scale = "（条文原文）" if st.get("text_scale") == "原文" else "（裁判要旨摘要）"
    lines = [
        f"> 📜 《{st['law']}》{st['article']}：{st['title']} {scale}",
        f"“{st['text']}”",
    ]
    if st.get("related_cases"):
        lines.append(f"相关判例：{'；'.join(st['related_cases'])}")
    return "\n".join(lines)
