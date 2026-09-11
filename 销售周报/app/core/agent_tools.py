"""
SalesAgent 战区总参谋长智能体 - 行动层工具箱 (Agent Tools)
包含 4 大战区督导取证工具链：
1. deal_substance_evaluator: 商机水分剥离与虚词测谎工具
2. pipeline_cliff_predictor: 商机漏斗蓄水与断崖预测工具
3. blocker_root_cause_tracer: 卡单死穴定性与归因溯源工具
4. tactical_dispatch_generator: 主管靶向派工与攻坚锦囊工具
"""
import re
from typing import Any, Dict, List, Optional


def deal_substance_evaluator(report_text: str, deals_text: Optional[str] = None) -> Dict[str, Any]:
    """
    商机水分剥离与虚词测谎工具
    检测销售周报中关于商机进展与成单描述是否存在模糊套话、虚夸承诺与关键决策人缺失。
    """
    text = f"{report_text} {deals_text or ''}"
    buzzword_flags: List[str] = []
    substance_signals: List[str] = []
    
    # 1. 拖延与虚饰话术匹配
    fuzzy_patterns = [
        (r"(正在走流程|走内部流程|走会签流程)", "使用「走流程」模糊表述，缺乏明确审批节点与时间表"),
        (r"(客户意向强烈|客户非常认可|客户兴趣很大)", "存在主观臆断倾向，缺乏关键决策人（KP）书面或实质立项凭证"),
        (r"(近期有望|预计很快|大概率能签|基本敲定)", "缺乏招投标/单一来源等合规采买程序支撑，成单时间存疑"),
        (r"(领导原则上同意|口头承诺|口头答应)", "依赖口头表态，未落实到商务实质或预算排期"),
        (r"(在保持沟通|积极跟进中|保持高频互动)", "过程动作繁复但缺乏阶段推进里程碑（Milestone）"),
    ]
    for pattern, reason in fuzzy_patterns:
        if re.search(pattern, text):
            buzzword_flags.append(reason)
            
    # 2. 真实硬核凭证匹配（脱水证据）
    proof_patterns = [
        (r"(首期款|预付款|打款|到账|定金)", "具备定金/预付款真实资金流水到账事实"),
        (r"(商务会签|盖章|签署补充协议|主协议已签)", "具备法务主合同/盖章推进等法律契约事实"),
        (r"(副总裁|总监|集团领导|李总|王总|张总|一把手|决策链)", "已攻坚至高层核心决策链（KP），非基层无效对接"),
        (r"(招投标|出标书|挂网|评审会|答辩)", "已进入正式采购招投标/专家评审阶段"),
        (r"(POC|技术测试|方案评审|架构对接)", "具备技术深度准入凭证，已度过初步接触期"),
    ]
    for pattern, evidence in proof_patterns:
        if re.search(pattern, text):
            substance_signals.append(evidence)

    # 3. 计算商机脱水含金量分值 (0 - 100)
    base_score = 75
    base_score -= len(buzzword_flags) * 12
    base_score += len(substance_signals) * 8
    substance_score = max(30, min(98, base_score))
    
    # 评级
    if substance_score >= 85:
        level = "high"
        level_label = "高可信 (核心硬核凭证充分)"
    elif substance_score >= 65:
        level = "medium"
        level_label = "一般 (存在部分模糊预期)"
    else:
        level = "low"
        level_label = "存疑 (充斥拖延套话，水分偏高)"

    return {
        "substance_score": substance_score,
        "level": level,
        "level_label": level_label,
        "buzzword_flags": buzzword_flags,
        "substance_signals": substance_signals,
    }


def pipeline_cliff_predictor(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    商机漏斗蓄水与断崖预测工具
    比对当期客拜量、线索增量与签约目标，推演未来 2~4 周是否存在商机枯竭型业绩断崖风险。
    """
    actual = report_data.get("actual_amount", 0.0)
    target = report_data.get("target_amount", 0.0)
    rate = report_data.get("completion_rate", 0.0)
    visits = report_data.get("visit_count", 0)
    leads = report_data.get("new_leads", 0)
    status = report_data.get("status", "on_track")

    cliff_flags: List[str] = []
    health_signals: List[str] = []

    # 1. 虚假繁荣断崖：当期虽然超额，但拜访和新线索严重断档
    if rate >= 90 and visits <= 3 and leads <= 1:
        cliff_flags.append("「虚假繁荣」断崖预警：本周主要依赖存量老客户签约，客拜与新增线索接近枯竭，未来 2~4 周将面临商机断档")
    
    # 2. 过程指标枯竭
    if visits == 0 and leads == 0:
        cliff_flags.append("过程指标全面归零：当期有效客拜与线索增量为 0，漏斗底池处于干涸状态")
    elif visits <= 2:
        cliff_flags.append(f"客拜动能严重不足（仅拜访 {visits} 家），难以支撑下阶段大额商机转化需求")

    # 3. 业绩落后且漏斗不足
    if rate < 60 and leads <= 2:
        cliff_flags.append(f"当期达成率仅 {rate}% 且新线索储备不足（仅 {leads} 条），双重失速风险加剧")

    # 正向蓄水指标
    if leads >= 4:
        health_signals.append(f"高价值储备充足：新增高价值商机线索 {leads} 条，漏斗前端蓄水良好")
    if visits >= 6:
        health_signals.append(f"客户拜访活跃：本周实地/深度客拜 {visits} 家，商机转化基盘稳固")

    # 计算断崖风险指数 (0 - 100，越高越危险)
    risk_index = 20
    risk_index += len(cliff_flags) * 25
    if rate < 70:
        risk_index += 15
    if visits <= 2:
        risk_index += 15
    cliff_risk_score = max(10, min(95, risk_index))

    if cliff_risk_score >= 65:
        cliff_level = "high"
        cliff_label = "高危断崖 (未来 2-4 周业绩面临急剧失速)"
    elif cliff_risk_score >= 40:
        cliff_level = "medium"
        cliff_label = "中度承压 (需重点监控下月商机储备)"
    else:
        cliff_level = "low"
        cliff_label = "健康平稳 (商机漏斗蓄水充沛)"

    return {
        "cliff_risk_score": cliff_risk_score,
        "cliff_level": cliff_level,
        "cliff_label": cliff_label,
        "cliff_flags": cliff_flags,
        "health_signals": health_signals,
    }


def blocker_root_cause_tracer(blockers_text: str, report_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    卡单死穴定性与归因溯源工具
    穿透销售填写的求助与卡单信息，自主诊断死穴归因与致命程度。
    """
    txt = (blockers_text or "").strip()
    if not txt or txt in ["无明显卡点，按计划推进", "无", "正常"]:
        return {
            "has_blocker": False,
            "severity": "none",
            "severity_label": "无明显卡点",
            "primary_cause": "正常推进",
            "diagnostic_notes": ["未报告严重外部阻碍或求助事项"],
            "requires_executive": False
        }

    causes: List[str] = []
    notes: List[str] = []
    severity = "medium"
    requires_executive = False

    # 1. 客户体制与反腐换届风险（高危致命）
    if re.search(r"(换届|反腐|领导班子调整|分管领导离职|人事变动|国企改制|立项冻结)", txt):
        causes.append("体制变动与换届停滞 (组织性死穴)")
        notes.append("遭遇客户决策层非正常人事换届或立项冻结，原沟通线索面临作废风险")
        severity = "critical"
        requires_executive = True

    # 2. 竞品低价围标与恶意价格战（高危）
    if re.search(r"(竞品|低价|价格战|友商|恶意降价|40%|拦路虎|丢单)", txt):
        causes.append("竞品恶意低价围标 (竞争性风险)")
        notes.append("竞争对手采取断崖式低价截胡策略，商务防线受压")
        if severity != "critical":
            severity = "high"
        requires_executive = True

    # 3. 法务合同与交付违约金争议（中/高危）
    if re.search(r"(法务|违约金|条款异议|按日万分之|商务条款|合同修改|盖章停滞)", txt):
        causes.append("法务合规与违约金争端 (内部/协同性障碍)")
        notes.append("客户对交付违约金或工期权责提出异议，卡在最终盖章签署关卡")
        if severity not in ["critical", "high"]:
            severity = "high"

    # 4. 高端技术答辩与专家资源短缺
    if re.search(r"(答辩|专家|架构师|方案支援|外聘教授|技术路线|技术评审)", txt):
        causes.append("高端专家资源协调 (战力缺口)")
        notes.append("面临重量级技术评审会或方案答辩，急需总部资深行业专家现场压阵")
        requires_executive = True

    # 兜底
    if not causes:
        causes.append("常规业务阻碍")
        notes.append(f"具体卡点描述：{txt[:60]}...")

    severity_labels = {
        "critical": "致命死穴 (客户组织变动，丢单率极高)",
        "high": "高危阻碍 (竞品抢单或合同纠纷，需立刻止血)",
        "medium": "一般协调 (资源协调与流程跟进)",
        "none": "无卡点"
    }

    return {
        "has_blocker": True,
        "severity": severity,
        "severity_label": severity_labels.get(severity, "一般协调"),
        "primary_cause": " / ".join(causes),
        "diagnostic_notes": notes,
        "requires_executive": requires_executive
    }


def tactical_dispatch_generator(report_data: Dict[str, Any], blocker_diag: Dict[str, Any]) -> Dict[str, Any]:
    """
    主管靶向派工与攻坚锦囊工具
    针对具体销售的卡单与标杆项目，生成落地可执行的主管派工动作与攻坚锦囊。
    """
    rep_name = report_data.get("salesperson", "销售代表")
    dept = report_data.get("department", "销售部")
    blockers = report_data.get("blockers", "")
    highlight = report_data.get("highlight_summary", "")
    status = report_data.get("status", "on_track")

    dispatch_plan: List[str] = []
    tactical_tips: List[str] = []

    # 1. 针对张翼德类（遭遇换届+竞品低价）
    if blocker_diag.get("severity") == "critical" or "换届" in blockers:
        dispatch_plan.append(f"【紧急高管陪访】销售主管协调大区总下周二（9月8日）亲自带队飞赴客户现场，约见新任分管信息化副总裁，重新确立战略合作框架")
        tactical_tips.append("【反制低价围标】坚决不打单纯价格战，亮出央国企 500 强交付成功率背书，突出竞品低价缩水交付的技术隐患，重塑评分标准")

    # 2. 针对赵子龙类（大单已签，但法务违约金卡单 + 技术答辩求助）
    elif "违约金" in blockers or "答辩" in blockers or "法务" in blockers:
        dispatch_plan.append(f"【法务协同限期办理】销售主管下周一上午组织法务专项沟通会，针对三期实施违约金条款出具封顶赔偿补充协议口径，保障周三前完成会签")
        dispatch_plan.append(f"【专家战力空投】责令总部解决方案中心（指定行业首席架构师）于下周二全程陪同 {rep_name} 参加中联重科技术路线答辩会")
        tactical_tips.append("【KA 标杆打法沉淀】将其成功锁单 150 万全域 ERP 的商务攻坚路径录制为 KA 战训案例，在周三销售例会上进行全员拆解推广")

    # 3. 针对关云长类（达成率尚可但客拜/线索下滑）
    elif status == "on_track" and report_data.get("visit_count", 0) <= 3:
        dispatch_plan.append(f"【促活督导】销售主管周一与 {rep_name} 进行 1v1 商机蓄水池复盘，下达硬性指标：下周实地拜访不少于 5 家新潜客，杜绝业绩断崖")
        tactical_tips.append("【存量客户深耕】指导其针对已成单老客户发起二次运维增购巡检，激活潜在线索")

    # 4. 针对黄汉升类（新人开拓）
    elif status == "growing":
        dispatch_plan.append(f"【新人导师协同】安排部门资深总监对 {rep_name} 的 POC 场景确认进行双人陪访，协助攻克商务谈判关卡")
        tactical_tips.append("【鼓励快节奏成单】对新人首战破局给予正向战报通报，强化团队士气")

    # 兜底
    else:
        dispatch_plan.append(f"【常规督导】主管常规核验 {rep_name} 推进节奏，跟进重点意向客户签约落地")
        tactical_tips.append("保持现有成单打法，防范合同签署及回款逾期风险")

    return {
        "target_salesperson": rep_name,
        "department": dept,
        "dispatch_actions": dispatch_plan,
        "tactical_tips": tactical_tips
    }
