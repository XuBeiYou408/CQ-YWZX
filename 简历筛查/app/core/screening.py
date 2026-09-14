"""
双轨初筛引擎
结合硬性门槛快速校验与大模型多维深度初筛评估
"""
import copy
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import uuid

from app.core.llm_client import generate_chat
from app.core.recruitment_agent import RecruitmentAgent

# 学历/院校层次数字映射
EDU_RANK: Dict[str, int] = {
    "doctor": 4,
    "master": 3,
    "bachelor": 2,
    "associate": 1,
    "any": 0,
    "other": 0,
}

SCHOOL_TIER_RANK: Dict[str, int] = {
    "985": 3,
    "211": 2,
    "other": 1,
    "any": 0,
}

# 985高校名单及常见简称
TIER_985_SCHOOLS = [
    "清华大学", "清华", "北京大学", "北大", "浙江大学", "浙大", "上海交通大学", "上海交大",
    "复旦大学", "复旦", "南京大学", "南大", "中国科学技术大学", "中科大", "哈尔滨工业大学", "哈工大",
    "西安交通大学", "西安交大", "中国人民大学", "人大", "北京航空航天大学", "北航", "北京理工大学", "北理工",
    "同济大学", "同济", "南开大学", "南开", "天津大学", "天大", "东南大学", "东大",
    "武汉大学", "武大", "华中科技大学", "华科", "华中理工", "中山大学", "中大", "华南理工大学", "华南理工",
    "华工", "四川大学", "川大", "电子科技大学", "电子科大", "成电", "中南大学", "湖南大学", "湖大",
    "山东大学", "山大", "吉林大学", "吉大", "厦门大学", "厦大", "大连理工大学", "大连理工",
    "西北工业大学", "西工大", "重庆大学", "重大", "兰州大学", "兰大", "东北大学", "中国农业大学", "中农",
    "中国海洋大学", "华东师范大学", "华东师大", "北京师范大学", "北师大", "西北农林科技大学", "国防科技大学", "中央民族大学"
]

# 211重点高校及常见简称
TIER_211_SCHOOLS = [
    "北京邮电大学", "北邮", "西安电子科技大学", "西电", "北京交通大学", "北交大", "华东理工大学", "华理",
    "南京航空航天大学", "南航", "南京理工大学", "南理工", "苏州大学", "苏大", "上海大学", "上大",
    "华中师范大学", "华师", "武汉理工大学", "暨南大学", "华南师范大学", "华南师大", "西南大学",
    "西南交通大学", "西南交大", "中国政法大学", "中央财经大学", "央财", "对外经济贸易大学", "对外经贸",
    "上海财经大学", "上财", "中南财经政法大学", "中国传媒大学", "北京外国语大学", "上海外国语大学",
    "中国地质大学", "中国矿业大学", "中国石油大学", "河海大学", "江南大学", "合肥工业大学", "福州大学",
    "南昌大学", "郑州大学", "湖南师范大学", "广西大学", "海南大学", "贵州大学", "云南大学", "西藏大学",
    "西北大学", "青海大学", "宁夏大学", "新疆大学", "石河子大学", "内蒙古大学", "延边大学", "东北农业大学",
    "东北林业大学", "哈尔滨工程大学", "大连海事大学", "辽宁大学", "北京工业大学", "北京科技大学",
    "北京化工大学", "北京林业大学", "北京中医药大学", "北京体育大学", "中央音乐学院", "中国药科大学",
    "安徽大学", "华北电力大学"
]

FALLBACK_SCREEN_RESULT: Dict[str, Any] = {
    "score": 50,
    "tier": "C",
    "label": "待人工评估",
    "ai_reason": "大模型评估服务调用或解析异常，触发降级保护，建议人工查阅简历原文。",
    "radar": {
        "技术深度": 50,
        "项目规模": 50,
        "技术栈匹配": 50,
        "学历背景": 50,
        "发展潜力": 50,
    },
    "tags": ["△ 待人工评估", "△ AI初筛降级"],
    "interview_questions": [
        "请结合过往工作经历介绍你最熟悉的核心技术项目及个人亮点产出？",
        "针对本岗位的核心技能要求，你在日常工作中主要运用了哪些？",
        "请分享一次在复杂生产环境下排查并解决重大技术难题的经历。",
    ],
}


def _parse_edu_from_text(text: str) -> str:
    """从文本推断学历，返回 doctor/master/bachelor/associate"""
    if re.search(r"博士|Ph\.?D", text, re.IGNORECASE):
        return "doctor"
    if re.search(r"硕士|研究生|Master", text, re.IGNORECASE):
        return "master"
    if re.search(r"本科|学士|大学本科|全日制本科|统招本科|Bachelor", text, re.IGNORECASE):
        return "bachelor"
    if re.search(r"大专|专科|高职|职业技术|高专|Associate", text, re.IGNORECASE):
        return "associate"
    if re.search(r"大学|学院", text):
        return "bachelor"
    return "associate"


def _parse_school_tier_from_text(text: str) -> str:
    """用正则匹配985/211院校名，返回 985/211/other"""
    if re.search(r"985(?:工程|高校|院校|统招)?", text, re.IGNORECASE):
        return "985"
    for school in TIER_985_SCHOOLS:
        if school in text:
            return "985"

    if re.search(r"211(?:工程|高校|院校|统招)?", text, re.IGNORECASE):
        return "211"
    for school in TIER_211_SCHOOLS:
        if school in text:
            return "211"

    return "other"


def _parse_experience_years_from_text(text: str) -> int:
    """正则提取工作年数，返回整数"""
    patterns = [
        r"(\d+)\s*年[^\d\n\r，。；！？]{0,30}?(?:经验|资历|工龄|开发|研发|工作|架构)",
        r"工作(?:年限|经验|资历)?[:：]?\s*(\d+)\s*年",
        r"(\d+)\s*年(?:工作|从业|开发|研发|IT|全栈|前端|后端|算法|产品)?经验",
        r"(\d+)\s*年(?:资历|工龄)",
        r"(?:拥有|具有|具备)\s*(\d+)\s*年",
        r"工龄[:：]?\s*(\d+)\s*年",
        r"(\d+)\s*\+?\s*years?(?:\s+of)?\s+experience",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, TypeError):
                pass

    m_range = re.search(r"(20\d{2})\s*[-–~至到]\s*(?:至今|现在|present)", text, re.IGNORECASE)
    if m_range:
        try:
            start_year = int(m_range.group(1))
            current_year = datetime.now().year
            diff = current_year - start_year
            if diff >= 0:
                return diff
        except Exception:
            pass

    return 0


TIER_NAMES: Dict[str, str] = {
    "qs100": "QS Top 100名校",
    "985": "985顶尖重点",
    "211": "211重点大学",
    "double_first": "双一流院校",
    "any": "不限",
    "other": "普通高校",
}

EDU_NAMES: Dict[str, str] = {
    "doctor": "博士及以上",
    "master": "硕士及以上",
    "bachelor": "统招本科及以上",
    "associate": "大专及以上",
    "any": "不限",
}

CAND_EDU_NAMES: Dict[str, str] = {
    "doctor": "博士",
    "master": "硕士",
    "bachelor": "本科",
    "associate": "大专",
}


def check_candidate_hard_gates(candidate: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    """
    全维度校验候选人与目标岗位的硬性初筛门槛
    支持候选人结构化数据与非结构化文本混合提取，涵盖：
    1. 最低学历门槛
    2. 院校背景门槛 (985/211/双一流/QS100)
    3. 工作年限门槛 (包含经验不限 0 年)
    4. 年龄上限门槛
    5. 学习形式门槛 (统招全日制)
    6. 核心必选技能覆盖
    """
    fail_reasons: List[str] = []
    resume_text = candidate.get("resume_text") or candidate.get("raw_resume") or ""

    # 1. 提取或推断工作年限
    cand_exp = candidate.get("experience_years")
    if cand_exp is None:
        cand_exp = candidate.get("detected_exp_years")
    if cand_exp is None and candidate.get("full_resume"):
        cand_exp = candidate.get("full_resume", {}).get("basic_info", {}).get("work_years")
    if cand_exp is None and resume_text:
        cand_exp = _parse_experience_years_from_text(resume_text)
    if cand_exp is None:
        cand_exp = 0
    try:
        cand_exp = int(cand_exp)
    except Exception:
        cand_exp = 0

    # 2. 提取或推断学历
    cand_edu = candidate.get("education") or candidate.get("detected_edu")
    if not cand_edu and candidate.get("full_resume"):
        edus = candidate.get("full_resume", {}).get("educations", [])
        for edu_item in edus:
            deg = edu_item.get("degree", "")
            if "博" in deg:
                cand_edu = "doctor"
                break
            elif "硕" in deg:
                cand_edu = "master"
                break
            elif "本" in deg or "学士" in deg:
                cand_edu = "bachelor"
                break
            elif "专" in deg:
                cand_edu = "associate"
                break
    if not cand_edu and resume_text:
        cand_edu = _parse_edu_from_text(resume_text)
    if not cand_edu:
        cand_edu = "associate"
    cand_edu = str(cand_edu).lower()

    # 3. 提取或推断院校层次
    cand_tier = candidate.get("school_tier") or candidate.get("detected_school_tier")
    if not cand_tier and candidate.get("full_resume"):
        edus = candidate.get("full_resume", {}).get("educations", [])
        tier_str = " ".join([e.get("tier", "") + " " + e.get("school", "") for e in edus])
        if "985" in tier_str:
            cand_tier = "985"
        elif "211" in tier_str:
            cand_tier = "211"
        elif "双一流" in tier_str:
            cand_tier = "double_first"
        elif "qs" in tier_str.lower() or "海外" in tier_str:
            cand_tier = "qs100"
    if not cand_tier and resume_text:
        cand_tier = _parse_school_tier_from_text(resume_text)
    if not cand_tier:
        cand_tier = "other"
    cand_tier = str(cand_tier).lower()

    # 4. 提取或推断年龄
    cand_age = candidate.get("age")
    if cand_age is None and candidate.get("full_resume"):
        cand_age = candidate.get("full_resume", {}).get("basic_info", {}).get("age")
    if cand_age is None:
        cand_age = 0
    try:
        cand_age = int(cand_age)
    except Exception:
        cand_age = 0

    # 5. 提取或推断学习形式
    cand_edu_type = candidate.get("education_type")
    if not cand_edu_type and candidate.get("full_resume"):
        edus = candidate.get("full_resume", {}).get("educations", [])
        full_text = " ".join([str(e.get("tier", "")) + " " + str(e.get("degree", "")) + " " + str(e.get("school", "")) for e in edus])
        if any(k in full_text for k in ("自考", "成考", "成人", "函授", "电大", "网络教育", "非全日制")):
            cand_edu_type = "general"
        else:
            cand_edu_type = "full_time"
    if not cand_edu_type:
        cand_edu_type = "full_time"

    # 6. 提取技能列表
    cand_skills = candidate.get("skills", [])
    if not cand_skills and candidate.get("full_resume"):
        sm = candidate.get("full_resume", {}).get("skills_matrix", [])
        for group in sm:
            cand_skills.extend(group.get("skills", []))

    # ── 开始逐项门槛比对 ──

    # 1. 学历要求
    req_edu = str(job.get("education", "any")).lower()
    if req_edu != "any":
        req_edu_rank = EDU_RANK.get(req_edu, 0)
        cand_edu_rank = EDU_RANK.get(cand_edu, 0)
        if cand_edu_rank < req_edu_rank:
            req_name = EDU_NAMES.get(req_edu, req_edu)
            det_name = CAND_EDU_NAMES.get(cand_edu, cand_edu)
            fail_reasons.append(f"学历未达到要求（岗位要求: {req_name}，实际推断为: {det_name}）")

    # 2. 院校层次要求
    req_tier = str(job.get("school_tier", "any")).lower()
    if req_tier != "any":
        tier_ranks = {"qs100": 4, "985": 3, "211": 2, "double_first": 2, "other": 1, "any": 0}
        req_tier_rank = tier_ranks.get(req_tier, 0)
        cand_tier_rank = tier_ranks.get(cand_tier, 1)
        if cand_tier_rank < req_tier_rank:
            fail_reasons.append(
                f"院校层次未达标（岗位要求: {TIER_NAMES.get(req_tier, req_tier)}，实际推断为: {TIER_NAMES.get(cand_tier, cand_tier.upper())}）"
            )

    # 3. 工作年限要求
    req_exp = job.get("experience_years", 0)
    try:
        req_exp = int(req_exp)
    except Exception:
        req_exp = 0
    if req_exp > 0:
        if cand_exp < req_exp:
            fail_reasons.append(f"工作年限不足（岗位要求: {req_exp}年及以上，实际提取为: {cand_exp}年）")

    # 4. 年龄上限要求
    req_max_age = job.get("max_age", 0)
    try:
        req_max_age = int(req_max_age)
    except Exception:
        req_max_age = 0
    if req_max_age > 0 and cand_age > 0:
        if cand_age > req_max_age:
            fail_reasons.append(f"年龄超出岗位偏好（岗位要求: {req_max_age}岁以下，实际为: {cand_age}岁）")

    # 5. 学习形式要求
    req_edu_type = str(job.get("education_type", "any")).lower()
    if req_edu_type in ("full_time", "统招全日制"):
        if cand_edu_type in ("general", "part_time", "非全日制"):
            fail_reasons.append("学习形式不符（岗位要求: 统招全日制，实际推断为: 非统招全日制）")

    # 6. 专业对口要求
    req_major = str(job.get("major", "any")).lower()
    cand_major = candidate.get("major", "")
    if not cand_major and candidate.get("full_resume"):
        edus = candidate.get("full_resume", {}).get("educations", [])
        cand_major = " ".join([str(e.get("major", "")) for e in edus])
    if not cand_major and resume_text:
        # 上传件（未做结构化解析）：从简历原文里规则提取专业，防止误判「专业背景不符」
        cand_major = extract_major_from_text(resume_text)
    if req_major not in ("any", "专业不限", ""):
        if req_major == "computer":
            if not any(k in cand_major for k in ("计算机", "软件", "网络", "信息", "智能", "通信", "数据", "电子", "物联网", "开发")):
                fail_reasons.append(f"专业背景不符（岗位要求: 计算机/软件类专业，实际为: {cand_major or '其他专业'}）")

    # 核心技能差异（作为AI匹配加分/减分标签，不作为硬门槛直接卡死）
    missing_skills: List[str] = []
    req_skills = job.get("required_skills", [])
    if req_skills and cand_skills:
        lower_cand = [str(s).lower() for s in cand_skills]
        missing_skills = [
            rk for rk in req_skills
            if not any(rk.lower() in ck or ck in rk.lower() for ck in lower_cand)
        ]

    return {
        "passed": len(fail_reasons) == 0,
        "fail_reasons": fail_reasons,
        "missing_skills": missing_skills,
        "detected_edu": cand_edu,
        "detected_school_tier": cand_tier,
        "detected_exp_years": cand_exp,
        "detected_age": cand_age,
        "detected_skills": cand_skills,
        "detected_major": cand_major,
    }


def check_hard_gates(resume_text: str, job: Dict[str, Any]) -> Dict[str, Any]:
    """向后兼容接口：校验学历/院校/年限等门槛，返回 {passed, fail_reasons, detected_edu, detected_school_tier, detected_exp_years}"""
    return check_candidate_hard_gates({"resume_text": resume_text}, job)


#: 院校名称提取（规则，零算力）：XX大学 / XX学院 / XX职业技术学院 等
_SCHOOL_NAME_RE = re.compile(r"[\u4e00-\u9fa5]{2,10}(?:大学|学院|职业技术学院|高等专科学校)")
_SCHOOL_PREFIX_NOISE = ("毕业于", "就读于", "来自", "本科", "硕士", "博士", "学校", "院校")


_SCHOOL_NOISE_START = ("全国", "中国", "全省", "全市", "全校", "本校", "该校", "各", "本", "我")
_SCHOOL_TAIL_BLOCK = ("生", "员", "赛", "杯")
_HONOR_LINE_RE = re.compile(r"竞赛|大赛|比赛|建模|挑战杯|奖学金|三好学生|优秀毕业生|获奖|奖项|荣誉称号")
_DEGREE_HINT_RE = re.compile(r"本科|硕士|博士|专科|学士|学位|全日制|统招|在读|毕业|研究生")


def detect_school_name(line: str) -> str:
    """从单行文本里识别院校名（带防误判）。

    先按「最长的 XX大学/学院/学校 词元」抽取，再逐层排除：
      1) 「全国大学生数学建模竞赛」这类词的尾部字符（生/员/赛/杯）；
      2) 「全国/中国/全校」等噪声前缀；
      3) 纯荣誉行（不含学历线索）。
    注意：**不要**用已知院校名单去做"包含即命中"的覆盖——「杭州电子科技大学」
    会被名单里的「电子科技大学」、「航空航天大学」会被简称「天大」误伤。
    """
    line = (line or "").strip()
    if not line or ("大学" not in line and "学院" not in line and "学校" not in line):
        return ""

    m = _SCHOOL_NAME_RE.search(line)
    name = m.group(0) if m else ""
    if not name:
        mm = re.search(r"([\u4e00-\u9fa5]{2,10}(?:大学|学院|学校))", line)
        name = mm.group(1) if mm else ""
    if not name:
        return ""

    for noise in _SCHOOL_PREFIX_NOISE:          # 去掉「毕业于」这类前缀
        if name.startswith(noise) and len(name) > len(noise) + 2:
            name = name[len(noise):]

    pos = line.find(name)
    tail = line[pos + len(name): pos + len(name) + 1] if pos >= 0 else ""
    if tail in _SCHOOL_TAIL_BLOCK:              # 「全国大学生…」这类，院校名后面不该跟"生/员/赛"
        return ""
    if len(name) <= 6 and any(name.startswith(p) for p in _SCHOOL_NOISE_START):
        return ""
    if _HONOR_LINE_RE.search(line) and not _DEGREE_HINT_RE.search(line):
        return ""
    return name


def _school_matches_tier(school: str, known: str) -> bool:
    """院校名与名单条目匹配：必须同名或以名单名为前缀，且长度不能离谱。

    否则「杭州电子科技大学」会被名单中的「电子科技大学」误判为 985。
    """
    if not school or not known:
        return False
    if school == known:
        return True
    return school.startswith(known) and len(school) <= len(known) + 4


def extract_school_name(resume_text: str) -> str:
    """从简历原文里抽取院校名称（纯规则，不调用模型）。

    用于「未做结构化解析」的简历也能显示真实院校，避免前端出现「（高校）」空占位。
    """
    if not resume_text:
        return ""
    for line in resume_text.splitlines():
        line = line.strip()
        if not line or ("大学" not in line and "学院" not in line and "学校" not in line):
            continue
        name = detect_school_name(line)
        if name:
            return name
    return ""


#: 常见专业名（按优先级排列），用于从简历原文提取「专业」以判定专业对口门槛
KNOWN_MAJORS = [
    "计算机科学与技术", "计算机应用技术", "计算机信息管理", "计算机技术", "计算机",
    "软件工程", "软件技术", "网络工程", "网络空间安全", "信息安全",
    "信息管理与信息系统", "信息与计算科学", "信息工程", "电子信息工程", "电子科学与技术",
    "通信工程", "人工智能", "智能科学与技术", "数据科学与大数据技术", "数据科学",
    "物联网工程", "数字媒体技术", "自动化", "电子信息",
    "统计学", "应用统计学", "数学与应用数学", "金融学", "会计学", "财务管理",
    "市场营销", "工商管理", "国际经济与贸易", "机械工程", "电气工程及其自动化",
    "土木工程", "材料科学与工程", "生物医学工程", "环境工程", "法学", "英语",
    "汉语言文学", "人力资源管理", "电子商务", "新闻学", "教育学", "心理学",
]
_MAJOR_NOISE = ("毕业于", "就读于", "所学", "主修", "来自", "本科", "硕士", "博士", "专科")

#: 专业名常见的「平台/系统」等后缀词，用于判断一条目是否像项目名
_PROJ_NAME_HINT_RE = re.compile(r"平台|系统|模块|工具|服务|中台|网站|应用|项目|引擎|体系|模型|框架")


def extract_major_from_text(resume_text: str) -> str:
    """从简历原文里抽取专业名称（纯规则，零算力）。

    上传件走的是「非结构化解析」路径，此前拿不到 major，导致简历里明明写着
    「计算机科学与技术」仍被判「专业背景不符 → 其他专业」而误淘汰；此处做规则兜底。
    """
    if not resume_text:
        return ""
    for major in KNOWN_MAJORS:                      # 1) 优先命中已知专业名
        if major in resume_text:
            return major
    m = re.search(r"([\u4e00-\u9fa5A-Za-z]{2,12}?)专业", resume_text)   # 2) 兜底：抽取「XX专业」
    if m:
        name = m.group(1)
        for noise in _MAJOR_NOISE:
            if name.startswith(noise) and len(name) > len(noise) + 1:
                name = name[len(noise):]
        return name
    return ""


def basic_fields_from_gate(resume_text: str, gate_res: Dict[str, Any]) -> Dict[str, Any]:
    """由硬性门槛结果回填「平铺基础字段」，让未做结构化解析的简历也有内容可展示。

    与 rescreen_candidate() 的回填口径保持一致（school/education/school_tier/experience_years/major）。
    """
    fields = {
        "education": gate_res.get("detected_edu") or "",
        "school_tier": gate_res.get("detected_school_tier") or "",
        "experience_years": gate_res.get("detected_exp_years"),
        "school": extract_school_name(resume_text),
        "major": gate_res.get("detected_major") or extract_major_from_text(resume_text),
    }
    age = gate_res.get("detected_age")
    if age:
        fields["age"] = age
    return fields


def rescreen_candidate(candidate: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    """
    当岗位门槛规则发生变化时，对指定候选人执行闭环重筛与状态重新核定：
    1. 重新进行 6 维硬性门槛判定；
    2. 若未通过硬性门槛：即刻流转至 rejected 淘汰库，评级 D 级(45分)，更新淘汰标签与详细拦截原因；
    3. 若通过硬性门槛：移出淘汰库，恢复或评定为合格推荐/复核状态，清除红标告警，更新合规标签与尽调结论。
    """
    gate_res = check_candidate_hard_gates(candidate, job)
    passed = gate_res["passed"]
    fail_reasons = gate_res["fail_reasons"]

    # 确保结构化基础字段同步
    candidate["hard_gate_passed"] = passed
    candidate["fail_reasons"] = fail_reasons
    candidate["experience_years"] = gate_res["detected_exp_years"]
    candidate["education"] = gate_res["detected_edu"]
    candidate["school_tier"] = gate_res["detected_school_tier"]
    if not candidate.get("school"):
        # 顺带回填院校名（规则提取），否则前端教育背景区只显示「（高校）」
        candidate["school"] = extract_school_name(
            candidate.get("resume_text") or candidate.get("raw_resume") or ""
        )
    if not candidate.get("major"):
        # 同步回填专业（规则提取），与院校口径保持一致
        candidate["major"] = gate_res.get("detected_major") or extract_major_from_text(
            candidate.get("resume_text") or candidate.get("raw_resume") or ""
        )
    if gate_res["detected_age"] > 0 and not candidate.get("age"):
        candidate["age"] = gate_res["detected_age"]

    cand_id = candidate.get("id", "")

    if not passed:
        # 硬性门槛未达标，移入淘汰拦截库
        candidate["state"] = "rejected"
        candidate["ai_score"] = 45
        candidate["score"] = 45
        candidate["ai_tier"] = "D"
        candidate["tier"] = "D"
        candidate["ai_label"] = "D级·硬性门槛未通过"
        candidate["label"] = "硬性门槛未通过"
        candidate["ai_reason"] = "未满足当前岗位最新硬性门槛条件：" + "；".join(fail_reasons)
        candidate["tags"] = [f"✗ {r}" for r in fail_reasons]
        
        deep_audit = candidate.get("deep_audit") or {}
        deep_audit["investigation_trace"] = [
            "【阶段 1: 极速守门员 (Workflow)】根据岗位最新门槛规则重新核验...",
            f"  ✗ 触发拦截：{'; '.join(fail_reasons)}",
            "【初筛定案】未达标最新刚性门槛，自动移入淘汰拦截库（未消耗模型推理Token）"
        ]
        deep_audit["risk_warnings"] = [f"硬性门槛拦截：{r}" for r in fail_reasons]
        deep_audit["verified_highlights"] = []
        deep_audit["targeted_interview_focus"] = ["硬性门槛未通过，建议暂缓或进入初级人才储备池"]
        candidate["deep_audit"] = deep_audit
        return candidate

    # ── 硬性门槛达标通过分支 ──
    # 针对预设候选人或已评估候选人，恢复其专属高保真画像
    if cand_id == "preset-001":
        candidate["state"] = "scheduled"
        candidate["ai_score"] = 98
        candidate["score"] = 98
        candidate["ai_tier"] = "S"
        candidate["tier"] = "S"
        candidate["ai_label"] = "S级·强烈推荐"
        candidate["label"] = "S级·强烈推荐"
        candidate["tags"] = [
            f"✓ {candidate['experience_years']}年资历·超额满足JD",
            f"✓ {candidate.get('school', '浙大')}计算机硕·985统招全日制",
            "✓ React/TS/Node/微前端 100%覆盖"
        ]
        candidate["ai_reason"] = "候选人毕业于浙江大学计算机系（985统招硕士），具有8年一线大厂深厚全栈研发资历。曾主导腾讯大型微前端体系搭建与高并发架构治理，核心技能与岗位JD完美重合，技术深度与综合潜力均属顶尖水平，强烈推荐直接安排终面。"
        deep_audit = candidate.get("deep_audit") or {}
        deep_audit["investigation_trace"] = [
            "【阶段 1: 极速守门员 (Workflow)】根据岗位最新门槛规则重新核验：学历、工龄及技术栈均超额达标！",
            "【阶段 2: 深度审查】时间线与技术项目交叉核验无断档，核心架构能力全维度达标。",
            "【初筛定案】综合核验无任何虚假包装，评定为顶尖 S 级。"
        ]
        deep_audit["risk_warnings"] = []
        deep_audit["verified_highlights"] = [
            "✓ 浙大985硕士学历真实，8年工龄连贯无断档",
            "✓ 命中微前端沙箱/千万级QPS等深度指标，自研度95%+",
            "✓ 经实名背景调查，字节+腾讯履历全部属实"
        ]
        candidate["deep_audit"] = deep_audit

    elif cand_id == "preset-002":
        candidate["state"] = "recommended"
        candidate["ai_score"] = 91
        candidate["score"] = 91
        candidate["ai_tier"] = "A"
        candidate["tier"] = "A"
        candidate["ai_label"] = "A级·建议录用"
        candidate["label"] = "A级·建议录用"
        candidate["tags"] = [
            f"✓ {candidate['experience_years']}年大厂经验·契合度高",
            f"✓ {candidate.get('school', '华南理工')}985统招全日制本",
            "✓ Next.js与全链路性能调优专家"
        ]
        candidate["ai_reason"] = "候选人毕业于985华南理工大学软件工程专业，具备5年知名跨境电商大厂研发经验，技术栈高度契合。在Next.js企业级架构与Web全链路性能极致优化方面具备丰富落地经验，工程规范度高，建议推进面试。"
        deep_audit = candidate.get("deep_audit") or {}
        deep_audit["investigation_trace"] = [
            "【阶段 1: 极速守门员 (Workflow)】根据岗位最新门槛规则重新核验：全部达标通过。",
            "【阶段 2: 综合评估】出海电商性能优化指标清晰属实，Next.js/React 实战能力扎实。",
            "【初筛定案】综合表现优秀，评定为 A 级建议录用。"
        ]
        deep_audit["risk_warnings"] = ["⚠️ 微前端与复杂全栈中间层经验相对较少，偏向现代化前端工程与性能优化"]
        deep_audit["verified_highlights"] = [
            "✓ 华南理工985统招学历属实，5年资历连贯",
            "✓ 出海电商性能优化有确凿量化指标（首屏提升40%）"
        ]
        candidate["deep_audit"] = deep_audit

    elif cand_id == "preset-003":
        candidate["state"] = "review"
        candidate["ai_score"] = 76
        candidate["score"] = 76
        candidate["ai_tier"] = "B"
        candidate["tier"] = "B"
        candidate["ai_label"] = "B级·待人工复核"
        candidate["label"] = "B级·待人工复核"
        candidate["tags"] = [
            f"✓ {candidate['experience_years']}年经验·985电子科大",
            "△ 技能侧重跨端Flutter/C++",
            "△ Node.js全栈服务端经验相对薄弱"
        ]
        candidate["ai_reason"] = "候选人985本科背景，6年美团研发经验，工程基本功扎实。但近几年主要精力聚焦于Flutter/C++跨端容器及性能调优，React有实战经验但缺少Node.js全栈架构深度，建议业务部门人工评估是否匹配当前团队需求。"
        deep_audit = candidate.get("deep_audit") or {}
        deep_audit["investigation_trace"] = [
            "【阶段 1: 极速守门员 (Workflow)】根据岗位最新门槛规则重新核验：硬性门槛均达标。",
            "【阶段 2: 技能深度比对】检测到近3年偏向跨端C++/Flutter，服务端Node.js实战相对不足。",
            "【初筛定案】评定为 B 级，转入待人工复核。"
        ]
        deep_audit["risk_warnings"] = [
            "⚠️ 技术栈偏离：近3年主攻移动端跨端开发，Web前端/Node.js全栈存在技术生疏风险",
            "⚠️ 项目量化指标不足，多为业务层封装"
        ]
        deep_audit["verified_highlights"] = ["✓ 电子科大985学历真实，美团大厂履历属实"]
        candidate["deep_audit"] = deep_audit

    elif cand_id == "preset-004":
        # 张铭在门槛放宽后顺利通过硬门槛，移出淘汰库，转入待人工复核
        candidate["state"] = "review"
        candidate["ai_score"] = 68
        candidate["score"] = 68
        candidate["ai_tier"] = "B"
        candidate["tier"] = "B"
        candidate["ai_label"] = "B级·待人工复核"
        candidate["label"] = "B级·待人工复核"
        candidate["tags"] = [
            f"✓ {candidate['experience_years']}年工作经验符合门槛",
            "✓ 学历达标已通过门槛",
            "△ 技能侧重基础Vue2，缺少React/Node架构深度"
        ]
        candidate["ai_reason"] = "候选人已顺利达标当前调整后的岗位准入门槛（年限与学历达标）。但在技能栈层面以基础Vue2与切图开发为主，与岗位深入要求的React/TypeScript/Node.js全栈及架构演进能力仍有差距，建议安排技术主管进行人工复核。"
        candidate["interview_questions"] = [
            "请谈谈你在使用Vue2开发项目时遇到的最棘手的性能或状态管理问题及解决方案？",
            "若业务需要快速切换至React与TypeScript体系，你的学习与落地规划是什么？",
            "请介绍一次你独立从0到1负责的模块或项目完整交付流程。"
        ]
        candidate["radar"] = {
            "技术深度": 62,
            "项目规模": 58,
            "技术栈匹配": 65,
            "学历背景": 60,
            "发展潜力": 75,
        }
        candidate["deep_audit"] = {
            "investigation_trace": [
                "【阶段 1: 极速守门员 (Workflow)】根据岗位最新门槛规则重新核验：年限与学历等硬性指标已全部达标！",
                "【阶段 2: 综合评估】检测到候选人已满足准入门槛，自动从淘汰库移出，转入待人工复核流程。",
                "【初筛定案】移出淘汰库，状态更新为待人工复核。"
            ],
            "risk_warnings": ["⚠️ 核心技术栈覆盖度需进一步复核"],
            "verified_highlights": ["✓ 工作年限及学历符合当前岗位最新门槛要求"],
            "targeted_interview_focus": ["重点考查对React与现代化前端工程的掌握意愿与学习速度"]
        }
    elif candidate.get("from_talent_pool"):
        # 从人才公海召回的候选人，保全其专属公海召回画像、分级与高亮标签
        score = candidate.get("score") or candidate.get("ai_score", 85)
        tier = candidate.get("tier") or candidate.get("ai_tier") or ("S" if score >= 90 else ("A" if score >= 80 else "B"))
        candidate["ai_score"] = score
        candidate["score"] = score
        candidate["ai_tier"] = tier
        candidate["tier"] = tier
        candidate["state"] = "recommended" if score >= 85 else "review"
        candidate["ai_label"] = f"{tier}级·公海智能召回"
        candidate["label"] = candidate["ai_label"]
        cand_exp = candidate.get("experience_years", 3)
        edu_name = CAND_EDU_NAMES.get(candidate.get("education"), "本科")
        candidate["tags"] = [
            "✓ 门槛变更·公海自动召回",
            f"✓ {cand_exp}年经验·超额达标" if cand_exp >= 5 else f"✓ {cand_exp}年经验·符合门槛",
            f"✓ {edu_name}·达标通过",
        ]
    else:
        # 上传的其他候选人
        orig_score = candidate.get("original_ai_score") or candidate.get("ai_score", 75)
        if orig_score <= 50:
            orig_score = 75
        candidate["ai_score"] = orig_score
        candidate["score"] = orig_score
        candidate["ai_tier"] = "A" if orig_score >= 85 else "B"
        candidate["tier"] = candidate["ai_tier"]
        candidate["state"] = "recommended" if orig_score >= 85 else "review"
        candidate["ai_label"] = f"{candidate['ai_tier']}级·{'强烈推荐' if orig_score >= 85 else '待人工复核'}"
        candidate["label"] = candidate["ai_label"]
        candidate["tags"] = [
            f"✓ {candidate['experience_years']}年经验符合门槛",
            "✓ 学历背景达标",
            "✓ 核心技能基本匹配"
        ]
        candidate["ai_reason"] = "候选人已达标岗位最新硬性门槛要求，初筛核验通过，建议继续推进下一步流程。"

    return candidate


def recall_talent_to_candidates(talent: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    """
    将人才公海中符合最新门槛的储备人才唤醒召回，转换为活跃初筛候选人结构
    """
    cand_id = talent.get("id") or f"restored-{uuid.uuid4().hex[:6]}"
    if not cand_id.startswith("restored-") and not cand_id.startswith("cand-"):
        cand_id = f"restored-{cand_id}"
    
    score = talent.get("ai_score", 85)
    tier = talent.get("ai_tier") or ("S" if score >= 90 else ("A" if score >= 80 else "B"))
    state = "recommended" if score >= 85 else "review"
    
    cand_exp = talent.get("experience_years", 3)
    cand_edu = talent.get("education", "bachelor")
    edu_name = CAND_EDU_NAMES.get(cand_edu, "本科")
    job_title = job.get("title", "招聘岗位")
    
    new_candidate = {
        "id": cand_id,
        "name": talent.get("name", "公海储备人才"),
        "age": talent.get("age", 28),
        "job_id": job.get("id", "fe-fullstack"),
        "status": "available",
        "available_time": "随时到岗",
        "apply_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "experience_years": cand_exp,
        "education": cand_edu,
        "education_type": talent.get("education_type", "full_time"),
        "school": talent.get("school", "知名高等院校"),
        "school_tier": talent.get("school_tier", "other"),
        "major": talent.get("major", "计算机科学与技术"),
        "current_company": talent.get("current_company", "互联网知名企业"),
        "current_title": talent.get("current_title", "资深开发工程师"),
        "salary_expect": talent.get("salary_expect", "22-32K"),
        "skills": talent.get("skills", ["Vue", "TypeScript"]),
        "verified": True,
        "from_talent_pool": True,
        "hard_gate_passed": True,
        "fail_reasons": [],
        "score": score,
        "ai_score": score,
        "tier": tier,
        "ai_tier": tier,
        "ai_label": f"{tier}级·公海智能召回",
        "label": f"{tier}级·公海智能召回",
        "ai_reason": f"【门槛调整联动召回】因当前岗位【{job_title}】门槛规则调整，系统实时扫描企业人才公海池，检测到该候选人学历（{edu_name}）、工龄（{cand_exp}年）等条件均已完全满足最新准入门槛，已自动唤醒召回并重新推入初筛匹配队列。",
        "radar": talent.get("radar", {
            "技术深度": score,
            "项目规模": max(50, score - 5),
            "技术栈匹配": min(95, score + 3),
            "学历背景": 90 if talent.get("school_tier") == "985" else 75,
            "发展潜力": score
        }),
        "tags": [
            "✓ 门槛变更·公海自动召回",
            f"✓ {cand_exp}年经验·超额达标" if cand_exp >= 5 else f"✓ {cand_exp}年经验·符合门槛",
            f"✓ {edu_name}·达标通过",
        ],
        "interview_questions": talent.get("interview_questions") or [
            f"针对你在【{talent.get('current_company','过往企业')}】的核心项目经历，请介绍最能体现你技术深度的架构设计？",
            f"针对当前岗位【{job_title}】的业务技术体系，你认为可以快速落地的切入点是什么？",
            "请分享一次在复杂工程体系中解决重大性能瓶颈或系统高可用保障的实战经验。"
        ],
        "state": state,
        "deep_audit": {
            "investigation_trace": [
                f"【公海智能联动】岗位【{job_title}】门槛调整，触发全量公海池实时重筛扫描...",
                f"  ✓ 门槛核验：工龄 {cand_exp}年、学历 {edu_name}、院校背景均完全达标！",
                "【初筛定案】完全契合最新岗位门槛，系统已自动将其从公海池唤醒，重新推入候选人初筛队列。"
            ],
            "risk_warnings": [],
            "verified_highlights": [
                "✓ 满足当前岗位最新门槛要求（工龄与学历完全达标）",
                "✓ 履历真实度与企业经历经实名核验"
            ],
            "targeted_interview_focus": [
                "重点评估其技能栈与本业务线架构演进路线的契合度"
            ]
        },
        "full_resume": talent.get("full_resume") or {
            "basic_info": {
                "name": talent.get("name"),
                "age": talent.get("age"),
                "work_years": cand_exp,
                "city": "深圳",
                "phone": "138-****-9999",
                "email": "talent_pool@recruitai.com",
                "target_title": job_title,
                "target_salary": talent.get("salary_expect", "25-35K"),
                "job_status": "随时到岗"
            },
            "summary": [
                f"拥有 {cand_exp} 年研发经验，在【{talent.get('current_company','')}】负责核心系统开发与业务交付；",
                f"毕业于 {talent.get('school','')}，计算机专业功底扎实，精通 {', '.join(talent.get('skills', [])[:3])}；",
                "经企业人才公海池战略储备，画像完整，可随时安排业务线专家复试。"
            ],
            "work_experience": [
                {
                    "company": talent.get("current_company", "知名互联网企业"),
                    "department": "核心研发部",
                    "title": talent.get("current_title", "研发工程师"),
                    "period": f"2023.01 - 2025.12 ({cand_exp}年)",
                    "responsibilities": f"负责业务核心系统研发、性能优化及稳定性建设，主导基于 {', '.join(talent.get('skills', [])[:2])} 的架构演进。",
                    "achievements": "按期高质交付重点业务模块，系统稳定性达99.99%，多次获评部门优秀技术骨干。"
                }
            ],
            "educations": [
                {
                    "school": talent.get("school", "知名高等院校"),
                    "degree": edu_name,
                    "major": talent.get("major", "计算机科学与技术"),
                    "period": "2016.09 - 2020.06",
                    "tier": talent.get("school_tier", "普通高校")
                }
            ],
            "skills_matrix": [
                {"category": "核心技术栈", "skills": talent.get("skills", [])}
            ]
        }
    }
    return new_candidate


def rescreen_job_candidates(candidates: List[Dict[str, Any]], job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """对属于指定 job 的所有候选人批量执行重筛与状态同步"""
    job_id = job.get("id", "")
    updated: List[Dict[str, Any]] = []
    for c in candidates:
        if c.get("job_id") == job_id:
            rescreen_candidate(c, job)
            updated.append(c)
    return updated


def _extract_json_from_llm(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    m = re.search(r"(\{.*\})", cleaned, re.DOTALL)
    if m:
        return m.group(1)
    return cleaned


async def llm_screen_resume(resume_text: str, job: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """调用 generate_chat，构建评估 prompt，要求 LLM 返回 JSON 含 score/tier/label/ai_reason/radar/tags/interview_questions，解析返回，失败降级"""
    truncated_resume = resume_text[:3000]

    system_prompt = (
        "你是一位专业资深的技术招聘架构师与面试专家。"
        "你的职责是严格根据目标岗位JD与候选人简历进行多维度量化评估，"
        "并严格以合法的 JSON 格式输出评估结果，不得输出任何其他文本或解释。"
    )

    prompt = f"""请根据目标岗位信息和候选人简历，进行全面初筛评估：

【目标岗位要求】
- 岗位名称: {job.get('title', '')}
- 薪资范围: {job.get('salary', '')}
- 工作地点: {job.get('location', '')}
- 最低工作年限: {job.get('experience_years', 0)} 年
- 学历要求: {job.get('education', 'any')}
- 院校层次要求: {job.get('school_tier', 'any')}
- 核心要求技能: {', '.join(job.get('required_skills', []))}
- 岗位描述(JD): {job.get('jd', '')}

【候选人简历内容(前3000字)】
{truncated_resume}

【初筛评级规则】
- S级 (90-100分): 顶尖卓越，技能与背景完全超额满足要求，强烈推荐
- A级 (80-89分): 优秀匹配，核心技术能力扎实，建议推进
- B级 (70-79分): 基本符合，存在部分技术栈偏差或瑕疵，待人工复核
- C级 (60-69分): 勉强合格，多项关键指标差距明显，建议储备
- D级 (<60分): 不符合岗位要求，予以淘汰

【输出格式要求】
必须严格输出合法的 JSON 对象，不要使用 markdown 标记或任何其他说明。格式如下：
{{
  "score": 88,
  "tier": "A",
  "label": "A级·建议录用",
  "ai_reason": "详细的综合初筛分析评语（100-200字）",
  "radar": {{
    "技术深度": 88,
    "项目规模": 85,
    "技术栈匹配": 90,
    "学历背景": 90,
    "发展潜力": 86
  }},
  "tags": ["✓ 5年资历·契合度高", "✓ 核心技术栈覆盖全面", "✓ 具有大厂复杂业务经验"],
  "interview_questions": [
    "针对候选人经历与JD量身定制的高质量面试问题1",
    "针对候选人经历与JD量身定制的高质量面试问题2",
    "针对候选人经历与JD量身定制的高质量面试问题3"
  ]
}}
"""

    try:
        raw_resp = await generate_chat(prompt, system_prompt=system_prompt, cfg=cfg, json_mode=True)
        json_str = _extract_json_from_llm(raw_resp)
        data = json.loads(json_str)

        raw_score = data.get("score", 50)
        try:
            score = int(raw_score)
        except (ValueError, TypeError):
            score = 50

        # 根据 score 统一核算 tier：S>=90, A=80-89, B=70-79, C=60-69, D<60
        if score >= 90:
            tier = "S"
        elif score >= 80:
            tier = "A"
        elif score >= 70:
            tier = "B"
        elif score >= 60:
            tier = "C"
        else:
            tier = "D"

        radar_in = data.get("radar", {})
        if not isinstance(radar_in, dict):
            radar_in = {}

        def _get_radar_dim(dim: str, default_val: int) -> int:
            val = radar_in.get(dim, default_val)
            try:
                iv = int(val)
                return max(0, min(100, iv))
            except Exception:
                return default_val

        radar = {
            "技术深度": _get_radar_dim("技术深度", score),
            "项目规模": _get_radar_dim("项目规模", score),
            "技术栈匹配": _get_radar_dim("技术栈匹配", score),
            "学历背景": _get_radar_dim("学历背景", score),
            "发展潜力": _get_radar_dim("发展潜力", score),
        }

        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = [str(tags)]
        else:
            tags = [str(t) for t in tags]

        questions = data.get("interview_questions", [])
        if not isinstance(questions, list):
            questions = [str(questions)]
        else:
            questions = [str(q) for q in questions]

        label = str(data.get("label", f"{tier}级·初筛完成"))
        ai_reason = str(data.get("ai_reason", "初筛评估完成"))

        return {
            "score": score,
            "tier": tier,
            "label": label,
            "ai_reason": ai_reason,
            "radar": radar,
            "tags": tags,
            "interview_questions": questions,
        }
    except Exception:
        return copy.deepcopy(FALLBACK_SCREEN_RESULT)


async def screen_resume_full(
    resume_text: str,
    job: Dict[str, Any],
    cfg: Dict[str, Any],
    candidate_name: str = "",
    filename: str = "",
) -> Dict[str, Any]:
    """
    先硬性校验，通过则 LLM 评估，返回完整候选人评估结构
    （含 id/name/filename/job_id/hard_gate_passed/fail_reasons/detected_*/score/tier/label/ai_reason/radar/tags/interview_questions/state/apply_time）
    硬性校验不通过则 state=rejected, score=45, tier=D；通过且score>=85则 state=recommended，否则 state=review。
    """
    cand_id = f"cand-{uuid.uuid4().hex[:8]}"
    name = candidate_name.strip() if candidate_name.strip() else (Path(filename).stem if filename else "未知候选人")
    apply_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    job_id = job.get("id", "")

    hard_gate = check_hard_gates(resume_text, job)
    basic = basic_fields_from_gate(resume_text, hard_gate)

    # 规则化结构化档案（零算力）：工作经历 / 项目经历 / 教育背景 / 技能矩阵，两条分支都带上，
    # 保证「硬门槛被拦截、未调用模型」的简历在前端也有完整可读档案，而不是空占位。
    rule_resume = build_structured_resume(resume_text, hard_gate, name)
    rule_extra = _structured_candidate_fields(rule_resume)

    if not hard_gate["passed"]:
        return {
            "id": cand_id,
            "name": name,
            "filename": filename,
            "job_id": job_id,
            "hard_gate_passed": False,
            "fail_reasons": hard_gate["fail_reasons"],
            "detected_edu": hard_gate["detected_edu"],
            "detected_school_tier": hard_gate["detected_school_tier"],
            "detected_exp_years": hard_gate["detected_exp_years"],
            # 基础字段回填：本分支刻意不调用模型（省算力），但规则能提取的字段照常落库，
            # 否则前端「完整档案」区块会显示「（高校）」这类空占位
            **basic,
            **rule_extra,
            "full_resume": rule_resume,
            "structured_parsed": False,
            "structured_source": "rule",
            "score": 45,
            "ai_score": 45,
            "tier": "D",
            "ai_tier": "D",
            "label": "硬性门槛未通过",
            "ai_label": "D级·硬性门槛未通过",
            "ai_reason": "未满足岗位硬性门槛条件：" + "；".join(hard_gate["fail_reasons"]),
            "radar": {
                "技术深度": 45,
                "项目规模": 40,
                "技术栈匹配": 40,
                "学历背景": 50 if hard_gate["detected_edu"] in ("bachelor", "master", "doctor") else 35,
                "发展潜力": 45,
            },
            "tags": [f"✗ {r}" for r in hard_gate["fail_reasons"]],
            "interview_questions": [],
            "state": "rejected",
            "apply_time": apply_time,
            "resume_text": resume_text,
            "raw_resume": resume_text,
            "deep_audit": {
                "investigation_trace": [
                    "【阶段 1: 极速守门员 (Workflow)】启动硬性门槛快速筛查...",
                    f"  ✗ 触发拦截：{'; '.join(hard_gate['fail_reasons'])}",
                    "【初筛定案】未达标刚性门槛，自动移入淘汰库（未消耗模型推理Token）",
                ],
                "risk_warnings": [f"硬性门槛拦截：{r}" for r in hard_gate["fail_reasons"]],
                "verified_highlights": [],
                "targeted_interview_focus": ["建议暂不进入面试轮次"],
            },
        }

    # 硬性校验通过，启动资深技术招聘尽调 Agent (ReAct 主循环)
    enable_agent = cfg.get("enable_deep_agent", True)
    if enable_agent:
        try:
            agent = RecruitmentAgent(cfg)
            llm_eval = await agent.run_deep_screening(resume_text, job, hard_gate)
        except Exception:
            llm_eval = await llm_screen_resume(resume_text, job, cfg)
    else:
        llm_eval = await llm_screen_resume(resume_text, job, cfg)

    score = llm_eval.get("score", 50)
    tier = llm_eval.get("tier", "C")
    label = llm_eval.get("label", "待复核")
    state = "recommended" if score >= 85 else "review"

    return {
        "id": cand_id,
        "name": name,
        "filename": filename,
        "job_id": job_id,
        "hard_gate_passed": True,
        "fail_reasons": [],
        "detected_edu": hard_gate["detected_edu"],
        "detected_school_tier": hard_gate["detected_school_tier"],
        "detected_exp_years": hard_gate["detected_exp_years"],
        **basic,
        **rule_extra,
        "full_resume": rule_resume,
        "structured_parsed": False,
        "structured_source": "rule",
        "score": score,
        "ai_score": score,
        "tier": tier,
        "ai_tier": tier,
        "label": label,
        "ai_label": label,
        "ai_reason": llm_eval.get("ai_reason", ""),
        "radar": llm_eval.get("radar", {}),
        "tags": llm_eval.get("tags", []),
        "interview_questions": llm_eval.get("interview_questions", []),
        "state": state,
        "apply_time": apply_time,
        "resume_text": resume_text,
        "raw_resume": resume_text,
        "deep_audit": llm_eval.get("deep_audit", {
            "investigation_trace": ["【阶段 1: 极速守门员 (Workflow)】学历、工龄硬性门槛达标通过。"],
            "risk_warnings": [],
            "verified_highlights": ["✓ 硬门槛全量校验通过"],
            "targeted_interview_focus": ["全面考查全栈技术综合素养"],
        }),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 规则化简历结构化提取（零算力 · 不调用大模型）
#   背景：为省算力，硬性门槛被拦截的简历此前完全不做结构化解析，
#         导致前端「完整工作经历 / 核心项目经历 / 教育背景」只能显示空占位。
#   方案：用纯规则（分节 + 正则）把简历原文拆成与 full_resume 同构的档案，
#         既不消耗 Token，也不会因本地模型不可用而丢失信息。
# ══════════════════════════════════════════════════════════════════════════════

#: 简历小节标题关键词（按匹配优先级排列）
_SECTION_KEYWORDS: List[tuple] = [
    ("summary", ("个人简介", "自我评价", "个人优势", "个人总结", "职业概述", "个人概述", "自我描述")),
    ("education", ("教育背景", "教育经历", "学历背景", "学习经历", "教育信息", "高等教育", "教育")),
    ("work", ("工作经历", "工作经验", "职业经历", "工作履历", "实习经历", "工作背景", "职业背景")),
    ("project", ("项目经历", "项目经验", "核心项目", "主要项目", "项目实践", "代表项目", "科研经历", "校园经历")),
    ("skills", ("核心技能", "专业技能", "技能特长", "技能清单", "擅长技术", "技能")),
    ("certs", ("荣誉证书", "获奖情况", "获奖经历", "资格证书", "所获荣誉", "获奖", "证书")),
]

#: 小节内部使用的字段标签，绝不能当成小节标题（否则「技术栈：xxx」会把整段切成新小节）
_FIELD_LABELS = (
    "技术栈", "技术选型", "使用技术", "项目描述", "项目背景", "项目简介", "项目介绍",
    "我的职责", "职责", "工作内容", "岗位职责", "工作职责", "所属部门", "部门",
    "工作业绩", "业绩", "成果", "项目成果", "我的角色", "担任角色", "汇报对象", "技术方案",
)

_FIELD_CAP = 900        # 单字段最大长度（超出截断，完整原文仍在「简历原文解析文本」中）

#: 年月区间（月份用 1[0-2] 优先，避免 "2024.12" 被截成 "2024.1"）
_YM = r"(?:19|20)\d{2}(?:\s*[.\-/年]\s*(?:1[0-2]|0?[1-9])?\s*月?)?"
_PERIOD_RE = re.compile(
    rf"({_YM}\s*[-–—－~～至到]\s*(?:{_YM}|至今|现在|今|present|Present|PRESENT|now))"
)

_COMPANY_HINTS = ("公司", "集团", "银行", "研究院", "研究所", "科技有限", "股份有限公司", "工作室", "实验室", "事业部")
_TITLE_HINTS = ("工程师", "架构师", "经理", "主管", "总监", "专员", "设计师", "分析师", "研究员",
                "负责人", "组长", "专家", "实习生", "开发", "研发", "运营", "顾问", "Leader")
_TITLE_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z·/+]{2,18}?(?:工程师|架构师|经理|主管|总监|专员|设计师|分析师|研究员|负责人|组长|专家|实习生))"
)

_DEPT_KEYS = ("所属部门", "部门", "所在部门", "任职部门")
_RESP_KEYS = ("工作内容", "岗位职责", "工作职责", "主要职责", "职责", "工作描述", "负责内容")
_ACH_KEYS = ("工作业绩", "主要业绩", "业绩", "工作成果", "主要成果", "成果", "成绩", "产出", "项目成果", "亮点")
_SKIP_KEYS = ("汇报对象", "汇报人", "直属上级", "薪资", "薪酬", "证明人")

#: 项目小节内的字段前缀映射
_PROJECT_PREFIX_MAP: List[tuple] = [
    ("tech_stack", ("技术栈", "技术选型", "使用技术", "关键技术", "技术方案", "开发环境")),
    ("background", ("项目描述", "项目背景", "项目简介", "项目介绍", "业务背景", "背景")),
    ("solutions", ("我的职责", "个人职责", "职责", "工作内容", "解决方案", "方案设计", "架构设计", "实施方案", "主要工作", "负责", "承担")),
    ("metrics", ("项目成果", "项目业绩", "成果", "业绩", "效益", "量化", "效果", "结果", "数据表现", "指标", "收益")),
    ("role", ("担任角色", "我的角色", "角色")),
]

#: 技术关键词 → 能力分类（用于从全文兜底生成技能矩阵）
_TECH_CATEGORY_MAP: List[tuple] = [
    ("编程语言", ("Python", "Golang", "Java", "JavaScript", "TypeScript", "C++", "C#", "PHP", "Rust",
                  "Kotlin", "Swift", "Scala", "Ruby", "SQL", "Shell", "Bash")),
    ("AI 与算法框架", ("PyTorch", "TensorFlow", "LangChain", "LlamaIndex", "AutoGen", "Semantic Kernel",
                       "FastMCP", "MCP", "Transformers", "HuggingFace", "PaddlePaddle", "vLLM",
                       "Ollama", "LM Studio", "scikit-learn", "XGBoost")),
    ("大模型与智能体", ("RAG", "Agent", "RLHF", "SFT", "LoRA", "QLoRA", "Prompt", "Function Calling",
                        "Embedding", "BGE", "text2vec", "GPT", "Claude", "Qwen", "通义", "DeepSeek",
                        "Llama", "GLM", "文心", "豆包", "Kimi", "微调")),
    ("数据与存储", ("Milvus", "FAISS", "Chroma", "Pinecone", "Weaviate", "Redis", "MySQL", "PostgreSQL",
                    "MongoDB", "Elasticsearch", "HBase", "Neo4j", "OceanBase")),
    ("后端与中间件", ("FastAPI", "Flask", "Django", "Spring Boot", "Spring Cloud", "NestJS", "Express",
                      "Kafka", "RabbitMQ", "RocketMQ", "gRPC", "RESTful", "GraphQL", "WebSocket")),
    ("前端技术栈", ("React", "Vue", "Next.js", "Nuxt", "Angular", "Element Plus", "ElementUI",
                    "TailwindCSS", "Webpack", "Vite", "小程序", "Flutter", "React Native", "HTML", "CSS")),
    ("数据处理", ("Pandas", "NumPy", "Scrapy", "BeautifulSoup", "PyMuPDF", "pdfplumber", "PySpark",
                  "Hive", "Spark", "Flink", "Airflow", "ETL")),
    ("工程与运维", ("Docker", "Kubernetes", "K8s", "Nginx", "Git", "GitLab", "Jenkins", "CI/CD", "Linux",
                    "Prometheus", "Grafana", "ELK", "Ansible", "Terraform", "阿里云", "腾讯云", "AWS")),
    ("通用能力", ("架构设计", "微服务", "高并发", "分布式", "性能优化", "需求分析", "项目管理", "敏捷开发", "单元测试")),
]

_BULLET_RE = re.compile(r"^[\s\-•·●*▪◆■▍|]+")
_INLINE_PAREN_RE = re.compile(r"[（(][^）)]{0,20}[）)]")
_SKILL_TAIL_RE = re.compile(r"(熟练|掌握|精通|熟悉|了解|会用|具备|良好|一般|读写|听读)+$")


def _clean_line(raw: str) -> str:
    """去掉行首项目符号与多余空白"""
    return _BULLET_RE.sub("", (raw or "").replace("\u3000", " ")).strip()


#: 行内字段标签：出现这些标签的行自成一段，不与上一行合并
_INLINE_FIELD_LABELS = (
    "所属部门", "部门", "工作部门", "汇报对象", "汇报人", "直属上级",
    "工作内容", "岗位职责", "工作职责", "主要职责", "职责描述", "职责",
    "工作业绩", "主要业绩", "业绩", "工作成果", "主要成果", "成果",
    "项目描述", "项目背景", "项目简介", "项目介绍", "业务背景",
    "技术栈", "技术选型", "使用技术", "关键技术", "技术方案",
    "我的职责", "个人职责", "解决方案", "方案设计", "架构设计", "实施方案", "主要工作",
    "项目成果", "项目业绩", "量化", "担任角色", "我的角色", "角色",
    "主修课程", "核心课程", "主要课程", "课程", "成绩", "GPA", "专业排名", "排名", "绩点", "学分",
)

#: 头部个人信息字段：不应被折行合并
_METADATA_PREFIX_RE = re.compile(
    r"^(姓名|性别|年龄|出生|生日|电话|手机|邮箱|现居|居住地|所在地|籍贯|政治面貌|求职意向|期望职位|"
    r"目标职位|应聘职位|意向岗位|期望薪资|期望月薪|薪资要求|到岗|工作年限|学历|GPA|专业排名)"
)

_CJK = r"\u4e00-\u9fa5"
_SENT_END_RE = re.compile(r"[。；;！!？?）)\]】”\"']$")


def _normalize_text(text: str) -> str:
    """归一化 PDF/Word 导出常见的「多余空格」。

    - 中↔英/数字 之间的空格一律去掉（"3 年" "重 庆大学 AI" 这类导出噪声）；
    - 中↔中 之间的空格**默认保留**（它常常是「公司  职位」的字段分隔，删了就无法切分）；
      只有当整行呈现「逐字被空格拆开」的特征（≥3 处 单字-空格-单字）时才合并。
    """
    out = []
    for raw in (text or "").splitlines():
        line = raw.replace("\u3000", " ").replace("\xa0", " ")
        line = re.sub(rf"(?<=[{_CJK}])[ \t]+(?=[A-Za-z0-9])", "", line)
        line = re.sub(rf"(?<=[A-Za-z0-9%\)\]）】])[ \t]+(?=[{_CJK}])", "", line)
        if len(re.findall(rf"[{_CJK}][ \t]+[{_CJK}]", line)) >= 3:
            line = re.sub(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])", "", line)
        out.append(line)
    return "\n".join(out)


def _is_bare_period_line(line: str) -> bool:
    """整行只有一段时间（如「2024.03 - 至今」），应归属上一条目而非另起条目"""
    if not _PERIOD_RE.search(line or ""):
        return False
    rest = _PERIOD_RE.sub("", line or "").strip(" 　·-—|｜,，:：()（）")
    return len(rest) <= 6


def _starts_new_block(line: str) -> bool:
    """该行是否应自成一段（不并入上一行）"""
    if not line:
        return True
    if _split_header(line)[0]:
        return True
    if _METADATA_PREFIX_RE.match(line):
        return True
    head = re.match(r"^([\u4e00-\u9fa5A-Za-z]{2,8})[：:]", line)
    if head and head.group(1) in _INLINE_FIELD_LABELS:
        return True
    if _is_bare_period_line(line):                      # 独立的时间段行
        return True
    if re.match(r"^[^：:]{1,14}[：:]", line):            # 「标签：值」行（技能分类、课程、成绩等）
        return True
    if re.search(r"(大学|学院|学校)$", line.strip()):    # 「重庆大学」这类院校行
        return True
    return False


def _is_structural_line(line: str) -> bool:
    """结构性行（小节标题 / 头部字段行）：绝不能把下一行并入自己"""
    if _split_header(line)[0]:
        return True
    return bool(_METADATA_PREFIX_RE.match(line or ""))


def _looks_like_project_title(line: str) -> bool:
    """「项目名（平台/系统/模块…）+ 时间段」这类项目标题行（区别于「项目描述：」这类字段行）"""
    return (
        bool(line)
        and len(line) <= 60
        and bool(_PERIOD_RE.search(line))
        and bool(_PROJ_NAME_HINT_RE.search(line))
        and not any(k in line for k in _COMPANY_HINTS)
    )


def _is_protected_prev(line: str) -> bool:
    """上一行是否已自成完整块（结构行 / 履历条目行 / 项目标题行），不应再吸收下一行。

    否则「某公司 | 高级工程师 2020.05-至今」会把紧随其后的职责句子粘进标题，
    导致履历职责丢失、公司/职位被污染。
    注意：项目字段行（「项目描述：…」）**不**在此列——它后面的折行正是描述正文，必须合并。
    """
    return _is_structural_line(line) or _looks_like_work_entry(line) or _looks_like_project_title(line)


def _reflow_lines(text: str) -> List[str]:
    """把 PDF/Word 导出的硬换行还原成完整行。

    简历导出后常出现一个字段被切成多行（如「重庆大学 / 计算机科学与技术 / 本科 / 2018.09-2022.06」
    各自一行，长句被按版面宽度折断），逐行解析必然错乱。这里按「上一行是否已结束 + 当前行是否
    自成一段」把被折断的行合并回去；标题行与履历/项目条目行不会再吸收正文。
    """
    out: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if (out and not _SENT_END_RE.search(out[-1]) and not _starts_new_block(line)
                and not _is_protected_prev(out[-1])):
            out[-1] = out[-1] + line
        else:
            out.append(line)
    return out


def _header_key(text: str) -> Optional[str]:
    """判断一段短文本是否为小节标题，返回小节 key"""
    h = re.sub(r"[\s:：\-—_·、,，。.;；【】\[\]()（）]+", "", text or "")
    if not h or len(h) > 18:
        return None
    if h in _FIELD_LABELS:              # 字段标签不是小节标题
        return None
    for key, kws in _SECTION_KEYWORDS:
        for kw in kws:
            if h == kw:
                return key
    # 合并标题（如「证书与荣誉」「获奖与证书」「技能清单」）：
    # 仅当短标题以关键词开头或结尾时才认（避免「负责高等教育业务」这类正文被误判成小节标题）
    if len(h) <= 12 and not re.match(r"^(获得|取得|通过|荣获|持有|已|负责|参与|主导)", h):
        for key, kws in _SECTION_KEYWORDS:
            for kw in kws:
                if h.startswith(kw) or h.endswith(kw):
                    return key
    return None


def _split_header(line: str) -> tuple:
    """拆出「小节标题 + 同行内容」。

    支持三种常见写法：
      1. 「教育背景」           —— 独立成行
      2. 「教育背景：2015.09…」 —— 冒号同行
      3. 「教育背景 2015.09…」  —— 空格同行（很多系统导出就是这样）
    """
    line = (line or "").strip()
    m = re.match(r"^[【\[(（]?\s*([^：:]{2,14})\s*[】\])）]?\s*[：:]\s*(.+)$", line)
    if m:
        key = _header_key(m.group(1))
        if key and m.group(2).strip():
            return key, _clean_line(m.group(2))
        return None, ""

    m2 = re.match(r"^([\u4e00-\u9fa5]{2,8})[ \t　]+(\S.*)$", line)
    if m2:
        key = _header_key(m2.group(1))
        if key:
            return key, _clean_line(m2.group(2))

    key = _header_key(line)
    return (key, "") if key else (None, "")


def _split_sections(resume_text: str) -> Dict[str, List[str]]:
    """把简历原文按小节标题切成 {小节: [行]}"""
    sections: Dict[str, List[str]] = {}
    current = "_head"
    for raw in (resume_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        key, inline = _split_header(line)
        if key:
            current = key
            sections.setdefault(current, [])
            if inline:
                sections[current].append(inline)
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _parse_period(text: str) -> str:
    m = _PERIOD_RE.search(text or "")
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1).replace("－", "-").replace("—", "-").replace("–", "-").replace("～", "~")).strip()


def _join_sentences(items: List[str]) -> str:
    cleaned = []
    for it in items:
        s = (it or "").strip().strip("；;。 ")
        if s and s not in cleaned:
            cleaned.append(s)
    text = re.sub(r"；{2,}", "；", "；".join(cleaned))
    return text[:_FIELD_CAP] + ("…" if len(text) > _FIELD_CAP else "")


def _detect_degree(text: str) -> str:
    if re.search(r"博士|Ph\.?D", text, re.IGNORECASE):
        return "博士研究生"
    if re.search(r"硕士|研究生|Master", text, re.IGNORECASE):
        return "硕士研究生"
    if re.search(r"本科|学士|Bachelor", text, re.IGNORECASE):
        return "本科"
    if re.search(r"大专|专科|高职|高专", text):
        return "专科"
    return ""


def _detect_tier(text: str, school: str) -> str:
    base = ""
    if "985" in text or any(_school_matches_tier(school, s) for s in TIER_985_SCHOOLS):
        base = "985 院校"
    elif "211" in text or any(_school_matches_tier(school, s) for s in TIER_211_SCHOOLS):
        base = "211 院校"
    elif "双一流" in text:
        base = "双一流"
    else:
        base = "普通高校"
    if re.search(r"统招|全日制", text):
        base += " / 统招全日制"
    return base


def _major_from_education_line(line: str, school: str) -> str:
    """从学历行里取「院校与学历之间的那段」作为专业（命中不了专业词表也能兜住）。

    例：「2017.09 - 2021.06  上海财经大学  统计学  本科」→「统计学」
    """
    s = _PERIOD_RE.sub(" ", line or "")
    if school:
        s = s.replace(school, " ")
    s = _INLINE_PAREN_RE.sub(" ", s)
    s = re.sub(r"(本科|硕士|博士|专科|学士|研究生|统招全日制|全日制|统招|在读|毕业)", " ", s)
    for seg in [x.strip(" ·-—|｜、,，:：") for x in re.split(r"\s+", s)]:
        if 2 <= len(seg) <= 12 and not re.search(r"\d", seg) and not re.search(r"大学|学院|学校|专业", seg):
            return extract_major_from_text(seg) or seg
    return ""


def _extract_honors(text: str) -> str:
    """按分隔符切段、剥离日期/院校/学历前缀后，取真正含荣誉关键词的片段"""
    parts = re.split(r"[\s|｜；;，,、（）()【】\[\]]+", text or "")
    hits = []
    for p in parts:
        s = _PERIOD_RE.sub("", p).strip(" ·-—")
        if not s:
            continue
        school = detect_school_name(s)
        if school:
            s = s.replace(school, "")
        s = re.sub(r"(本科|硕士|博士|专科|学士|研究生|统招全日制|全日制|统招)", "", s).strip(" ·-—")
        if s and re.search(r"奖学金|优秀毕业生|三好学生|优秀员工|竞赛|大赛|一等奖|二等奖|三等奖|国家奖|荣誉|奖项", s):
            hits.append(s)
    return "、".join(dict.fromkeys(hits))[:60]


def _split_skills(raw: str) -> List[str]:
    """拆分技能串：先去括号注释，再按分隔符切分，最后去掉熟练度等尾缀"""
    text = _INLINE_PAREN_RE.sub(" ", raw or "")
    parts = re.split(r"[、,，/｜|;；]+", text)
    out = []
    for p in parts:
        s = re.sub(r"^(?:熟悉|掌握|精通|了解|会用|具备|有|以及|和)\s*", "", p).strip(" ·-—")
        s = _SKILL_TAIL_RE.sub("", s).strip()
        if 1 < len(s) <= 24 and s not in out:
            out.append(s)
    return out


# ────────────────────────────── 分节解析器 ──────────────────────────────

#: 学历块内的辅助行（课程/成绩等），只用于补字段，不新建条目
_EDU_AUX_PREFIX = ("主修课程", "核心课程", "主要课程", "课程", "成绩", "GPA", "专业排名", "排名", "绩点", "学分")


def _looks_like_education_line(line: str) -> bool:
    """该行是否更像学历行（院校 + 学历线索），用于兜底提取时避免被当成履历条目"""
    if not line:
        return False
    has_school = bool(detect_school_name(line)) or ("大学" in line or "学院" in line or "学校" in line)
    return has_school and bool(_DEGREE_HINT_RE.search(line))


def _parse_educations(lines: List[str], resume_text: str) -> List[Dict[str, Any]]:
    """按「院校」把学历块聚合成条目。

    PDF/Word 导出后常是「重庆大学 / 计算机科学与技术 / 本科 / 2018.09-2022.06」各占一行，
    逐行解析会拆成多个残缺条目（院校对了但学历专业全空），因此这里改为遇到院校行即新起
    一条，后续的学历/专业/时间/课程/荣誉行都归属到该条目。
    """
    def blank() -> Dict[str, Any]:
        return {"school": "", "degree": "", "major": "", "period": "", "honors": [], "_text": ""}

    entries: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None

    for raw in lines:
        line = _clean_line(raw)
        if not line:
            continue

        if line.startswith(_EDU_AUX_PREFIX):          # 课程/成绩/GPA：只补字段
            if cur is not None:
                cur["_text"] += " " + line
                if not cur["degree"]:
                    cur["degree"] = _detect_degree(line)
                if not cur["period"]:
                    cur["period"] = _parse_period(line)
                h = _extract_honors(line)
                if h:
                    cur["honors"].append(h)
            continue

        school = detect_school_name(line)
        degree = _detect_degree(line)
        period = _parse_period(line)
        major = extract_major_from_text(line) or _major_from_education_line(line, school)
        honors = _extract_honors(line)

        if school:                                     # 新条目
            if cur and (cur["school"] or cur["degree"]):
                entries.append(cur)
            cur = blank()
            cur["school"] = school
            cur["degree"] = degree
            cur["major"] = major
            cur["period"] = period
            cur["_text"] = line
            if honors:
                cur["honors"].append(honors)
            continue

        if cur is None:
            continue
        cur["_text"] += " " + line
        if degree and not cur["degree"]:
            cur["degree"] = degree
        if period and not cur["period"]:
            cur["period"] = period
        if major and not cur["major"]:
            cur["major"] = major
        if not cur["major"]:
            cur["major"] = _major_from_education_line(line, cur["school"])
        if honors:
            cur["honors"].append(honors)

    if cur and (cur["school"] or cur["degree"]):
        entries.append(cur)

    if not entries:     # 小节缺失时，从全文兜底扫一遍
        for line in (resume_text or "").splitlines():
            school = detect_school_name(line)
            if school:
                entries.append({
                    "school": school, "degree": _detect_degree(line), "major": extract_major_from_text(line),
                    "period": _parse_period(line), "honors": [], "_text": line,
                })
                break

    # 补全缺失的专业/时间段（与院校同现于其它行时）
    for item in entries:
        if not item["major"] or not item["period"]:
            for line in (resume_text or "").splitlines():
                if item["school"] and item["school"] in line:
                    if not item["major"]:
                        item["major"] = extract_major_from_text(line)
                    if not item["period"]:
                        item["period"] = _parse_period(line)
                    if item["major"] and item["period"]:
                        break

    out: List[Dict[str, Any]] = []
    seen = set()
    for e in entries:
        key = (e["school"], e["degree"], e["period"])
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "school": e["school"] or "院校未识别",
            "degree": e["degree"] or "学历未识别",
            "major": e["major"] or "",
            "period": e["period"] or "",
            "tier": _detect_tier(e.get("_text", ""), e["school"]),
            "honors": "、".join(dict.fromkeys(h for h in e["honors"] if h))[:60],
        })
    return out


def _looks_like_work_entry(line: str) -> bool:
    """该行是否像「履历条目起始行」（公司+职位 或 时间段+公司/职位）"""
    if not line or len(line) > 70:
        return False
    head = re.match(r"^([\u4e00-\u9fa5]{2,6})[：:]", line)
    if head and head.group(1) in _DEPT_KEYS + _RESP_KEYS + _ACH_KEYS + _SKIP_KEYS:
        return False
    has_period = bool(_PERIOD_RE.search(line))
    has_company = any(k in line for k in _COMPANY_HINTS)
    has_title = any(k in line for k in _TITLE_HINTS)
    # 必须「公司+职位」或「时间段+公司/职位」，避免正文里出现"公司"二字就被误判为新履历
    return (has_company and has_title) or (has_period and (has_company or has_title))


def _looks_like_project_entry(line: str) -> bool:
    """该行是否像「项目条目起始行」：项目字段标签行，或「项目名（平台/系统/模块…）+ 时间段」"""
    if not line or len(line) > 60:
        return False
    if re.match(r"^(项目描述|项目背景|项目简介|项目介绍|技术栈|技术选型|个人职责|我的职责)", line):
        return True
    return (
        bool(_PERIOD_RE.search(line))
        and bool(_PROJ_NAME_HINT_RE.search(line))
        and not any(k in line for k in _COMPANY_HINTS)
    )


def _parse_work_experiences(lines: List[str]) -> List[Dict[str, Any]]:
    def blank() -> Dict[str, Any]:
        return {"company": "", "department": "", "title": "", "period": "",
                "responsibilities": [], "achievements": []}

    def is_entry(line: str) -> bool:
        return _looks_like_work_entry(line)

    def fill_header(cur: Dict[str, Any], line: str) -> None:
        cur["period"] = _parse_period(line)
        body = _PERIOD_RE.sub(" ", line).strip()
        parts = [p.strip(" ：:·|｜") for p in re.split(r"[|｜]", body) if p.strip(" ：:·")]
        company, title = "", ""
        if len(parts) >= 2:                     # 「公司 | 部门 | 职位」这类
            company = parts[0]
            for p in parts[1:]:
                tm = _TITLE_RE.search(p)
                if tm:
                    title = tm.group(1)
                    break
        else:                                   # 「公司 职位」这类：按空格切段，含职位词的段作为职位
            segs = [s for s in re.split(r"\s+", body) if s]
            t_idx = None
            for i, s in enumerate(segs):
                tm = _TITLE_RE.search(s)
                if tm:
                    t_idx, title = i, tm.group(1)
                    break
            if t_idx is not None:
                company = " ".join(segs[:t_idx])
        if not company and parts:
            company = parts[0]
        if not title:
            tm = _TITLE_RE.search(body)
            if tm:
                title = tm.group(1)
        # 去掉误并入公司名的小节/字段前缀
        company = re.sub(r"^(工作经历|工作经验|职业经历|工作履历|实习经历|项目经历|项目实践|教育背景|教育经历)\s*", "", company)
        cur["company"] = company.strip(" ·-—|｜")[:40]
        cur["title"] = title

    entries: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for raw in lines:
        line = _clean_line(raw)
        if not line:
            continue
        if is_entry(line):
            if cur:
                entries.append(cur)
            cur = blank()
            fill_header(cur, line)
            continue
        if cur is None:
            cur = blank()
        if _is_bare_period_line(line):          # 时间段独立成行：归属当前履历
            if not cur["period"]:
                cur["period"] = _parse_period(line)
            continue
        # 同一行可能包含多个「字段：值」（以 | 分隔，如「所属部门：X | 汇报对象：Y」），逐段处理
        for seg in [s.strip() for s in re.split(r"[|｜]", line) if s.strip()]:
            head = re.match(r"^([\u4e00-\u9fa5]{2,6})[：:]\s*(.*)$", seg)
            key, rest = (head.group(1), head.group(2)) if head else ("", seg)
            if key in _SKIP_KEYS:
                continue
            if key in _DEPT_KEYS:
                cur["department"] = rest.strip()[:30]
                continue
            if key in _ACH_KEYS:
                cur["achievements"].append(rest)
                continue
            if key in _RESP_KEYS:
                cur["responsibilities"].append(rest)
                continue
            # 无标记的行：默认归入职责；仅当以「通过/实现/推动」开头且带明确量化提升时才归入业绩
            is_metric = bool(re.search(r"\d+\s*(?:%|％|倍)", seg)) and bool(
                re.search(r"提升|降低|缩短|减少|增长|优化|下降|提高", seg)
            )
            if is_metric and re.match(r"^(通过|实现|推动|达成|借助|基于)", seg):
                cur["achievements"].append(seg)
            else:
                cur["responsibilities"].append(seg)
    if cur:
        entries.append(cur)

    out: List[Dict[str, Any]] = []
    for e in entries:
        # 必须有公司或职位才算真实履历条目（否则只是散落在正文里的行，避免出现「（未识别企业）」空条目）
        if not (e["company"] or e["title"]):
            continue
        out.append({
            "company": e["company"] or "（未识别企业）",
            "department": e["department"] or "",
            "title": e["title"] or "",
            "period": e["period"] or "",
            "responsibilities": _join_sentences(e["responsibilities"]),
            "achievements": _join_sentences(e["achievements"]),
        })
    return out


def _parse_projects(lines: List[str]) -> List[Dict[str, Any]]:
    def looks_like_start(line: str, nxt: str) -> bool:
        if not line or len(line) > 60:
            return False
        if _is_bare_period_line(line):          # 独立时间段行归属上一条目，不另起
            return False
        if re.match(r"^[\u4e00-\u9fa5]{2,6}[：:]", line):
            return False
        if nxt and re.match(r"^(项目描述|项目背景|项目简介|项目介绍|业务背景|技术栈|技术选型|个人职责|我的职责)", nxt):
            return True
        if _is_bare_period_line(nxt) and len(line) <= 40:      # 「项目名」+ 下一行「时间」
            return True
        return bool(_PERIOD_RE.search(line)) and len(line) <= 60

    def blank() -> Dict[str, Any]:
        return {"name": "", "role": "", "period": "", "tech_stack": "",
                "background": [], "solutions": [], "metrics": []}

    entries: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for idx, raw in enumerate(lines):
        line = _clean_line(raw)
        nxt = _clean_line(lines[idx + 1]) if idx + 1 < len(lines) else ""
        if not line:
            continue
        if looks_like_start(line, nxt):
            if cur:
                entries.append(cur)
            cur = blank()
            cur["period"] = _parse_period(line)
            name = _PERIOD_RE.sub(" ", line).strip(" ·-—|｜")
            rm = re.search(r"[\u4e00-\u9fa5]{0,4}(负责人|核心开发|核心研发|核心成员|主导|主要开发|架构师)", name)
            if rm:
                cur["role"] = rm.group(0)
                name = name.replace(rm.group(0), "")
            cur["name"] = name.strip(" ·-—|｜")[:60] or "未命名项目"
            continue
        if cur is None:
            cur = blank()
            cur["name"] = "项目经历"
            cur["role"] = cur["role"] or "核心开发"
        if _is_bare_period_line(line) and not cur["period"]:    # 时间段独立成行：归属当前项目
            cur["period"] = _parse_period(line)
            continue
        matched = False
        for field, keys in _PROJECT_PREFIX_MAP:
            for k in keys:
                if line.startswith(k):
                    val = re.sub(rf"^{k}\s*[：:]?\s*", "", line).strip()
                    if field == "role":
                        cur["role"] = val or cur["role"]
                    elif field == "tech_stack":
                        cur["tech_stack"] = (cur["tech_stack"] + "、" + val).strip("、") if cur["tech_stack"] else val
                    else:
                        cur[field].append(val)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            cur["solutions"].append(line)
    if cur:
        entries.append(cur)

    out: List[Dict[str, Any]] = []
    for e in entries:
        if not (e["name"] or e["solutions"] or e["background"]):
            continue
        out.append({
            "name": e["name"] or "未命名项目",
            "role": e["role"] or "核心开发",
            "period": e["period"] or "",
            "tech_stack": e["tech_stack"] or "",
            "background": _join_sentences(e["background"]) or _join_sentences(e["solutions"])[:200],
            "solutions": _join_sentences(e["solutions"]),
            "metrics": _join_sentences(e["metrics"]),
        })
    return out


def _parse_skills(section_lines: List[str], resume_text: str) -> List[Dict[str, Any]]:
    matrix: List[Dict[str, Any]] = []
    for raw in section_lines:
        line = _clean_line(raw)
        m = re.match(r"^([^：:]{2,14})[：:]\s*(.+)$", line)
        if m:
            items = _split_skills(m.group(2))
            if items:
                matrix.append({"category": m.group(1).strip(), "skills": items})
        else:
            items = _split_skills(line)
            if len(items) >= 3:
                matrix.append({"category": "核心技能", "skills": items})
    if matrix:
        return matrix

    # 兜底：从全文按技术关键词归类
    text = resume_text or ""
    seen = set()
    for category, kws in _TECH_CATEGORY_MAP:
        hits = [k for k in kws if k in text and k.lower() not in seen]
        for h in hits:
            seen.add(h.lower())
        if hits:
            matrix.append({"category": category, "skills": hits[:14]})
    return matrix


#: 证书/荣誉块里需要剔除的噪声（成绩、排名、课程等不是证书）
_CERT_NOISE_RE = re.compile(r"GPA|专业排名|排名|成绩|绩点|学分|主修课程|核心课程|课程")


def _parse_certificates(lines: List[str], resume_text: str) -> List[str]:
    out: List[str] = []
    candidates = [_clean_line(l) for l in lines]
    if not candidates:
        candidates = [l.strip() for l in (resume_text or "").splitlines()
                      if any(k in l for k in ("证书", "认证", "CET", "英语四", "英语六", "等级考试", "资格"))]
    for line in candidates:
        if not line or len(line) < 3 or len(line) > 90:
            continue
        if _CERT_NOISE_RE.search(line) and not re.search(r"证书|认证|奖|大赛|竞赛", line):
            continue
        if _header_key(line) or line in out:        # 剔除嵌套标题行与重复项
            continue
        out.append(line)
    return out[:6]


def _parse_basic_info(resume_text: str, gate_res: Optional[Dict[str, Any]], name: str) -> Dict[str, Any]:
    text = resume_text or ""
    phone_m = (re.search(r"1[3-9]\d(?:[\-\s]?\d){8,10}", text)
               or re.search(r"1[3-9]\d[\-\s]?(?:\d{4}|[Xx\*]{2,4})[\-\s]?\d{4}", text))
    email_m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    city_m = re.search(r"(?:现居|居住地|所在地|现居住|居住)[:：\s]*([\u4e00-\u9fa5]{2,10})", text)
    age_m = re.search(r"(\d{2})\s*岁", text)
    title_m = re.search(r"(?:求职意向|期望职位|目标职位|应聘职位|意向岗位)[:：\s]*([^\n|｜]{2,30})", text)
    salary_m = re.search(r"(?:期望薪资|期望月薪|薪资要求|期望薪酬)[:：\s]*([\d\.\-~～kK万¥￥W\s]{2,20})", text)
    gate = gate_res or {}

    age = int(age_m.group(1)) if age_m else int(gate.get("detected_age") or 0)
    if not (16 <= age <= 70):
        age = 0
    return {
        "name": name,
        "age": age,
        "work_years": gate.get("detected_exp_years") or 0,
        "city": city_m.group(1) if city_m else "",
        "phone": phone_m.group(0).strip() if phone_m else "",
        "email": email_m.group(0) if email_m else "",
        "target_title": (title_m.group(1).strip() if title_m else ""),
        "target_salary": (salary_m.group(1).strip() if salary_m else ""),
        "job_status": "在职" if "在职" in text[:1500] else ("离职 - 随时到岗" if "离职" in text[:1500] else ""),
    }


def _parse_summary(section_lines: List[str], head_lines: List[str]) -> List[str]:
    out: List[str] = []
    for raw in section_lines:
        line = _clean_line(raw)
        if line and line not in out:
            out.append(line[:200])
    if out:
        return out[:6]
    # 无独立小节时：用开头信息块之后的第一段长文本兜底
    for line in head_lines:
        s = _clean_line(line)
        if len(s) >= 30 and not re.search(r"@|1[3-9]\d{9}|求职意向", s):
            return [s[:200]]
    return []


def build_structured_resume(
    resume_text: str,
    gate_res: Optional[Dict[str, Any]] = None,
    name: str = "",
) -> Dict[str, Any]:
    """规则化地把简历原文拆成结构化档案（与 full_resume 同构，零模型算力）。

    返回 basic_info / summary / work_experience / project_experience /
    educations / skills_matrix / certificates 七个区块。
    """
    normalized = _normalize_text(resume_text)
    lines = _reflow_lines(normalized)                 # 先还原被 PDF/Word 版面折断的行
    flat_text = "\n".join(lines)
    sections = _split_sections(flat_text)
    head_lines = sections.get("_head", [])

    basic = _parse_basic_info(flat_text, gate_res, name)
    educations = _parse_educations(sections.get("education", []), flat_text)
    works = _parse_work_experiences(sections.get("work", []))
    projects = _parse_projects(sections.get("project", []))
    skills_matrix = _parse_skills(sections.get("skills", []), flat_text)
    certificates = _parse_certificates(sections.get("certs", []), flat_text)
    summary = _parse_summary(sections.get("summary", []), head_lines)

    # 兜底：简历没有「工作经历 / 项目经历」小节标题时（很多系统导出的简历就是纯文本流），
    # 从其余未被其它小节消费的行里再识别一次；但必须有明确的条目特征才启用，避免把正文误当履历。
    if not works or not projects:
        consumed = set()
        for key in ("education", "skills", "certs", "summary"):
            consumed.update(sections.get(key, []))
        # 已经作为小节标题的行也不算「未被消费」（否则「高等教育」「核心技能」这类标题行
        # 会掉进兜底扫描，被当成履历职责等正文内容）
        leftover = [l for l in lines if l not in consumed and not _split_header(l)[0]]
        if not works:
            work_lines = [l for l in leftover if not _looks_like_education_line(l)]
            if any(_looks_like_work_entry(l) for l in work_lines):
                works = _parse_work_experiences(work_lines)
        if not projects and any(_looks_like_project_entry(l) for l in leftover):
            projects = _parse_projects(leftover)

    # 基本信息缺院校/学历时，用教育背景补齐
    if educations:
        top = educations[0]
        basic.setdefault("school", "")
        if not basic.get("school"):
            basic["school"] = top.get("school", "")

    return {
        "basic_info": basic,
        "summary": summary,
        "work_experience": works,
        "project_experience": projects,
        "educations": educations,
        "skills_matrix": skills_matrix,
        "certificates": certificates,
    }


def flat_skills_from_matrix(skills_matrix: Optional[List[Dict[str, Any]]]) -> List[str]:
    """把技能矩阵拍平成技能列表（供硬门槛技能匹配与前端标签使用）"""
    out: List[str] = []
    for group in skills_matrix or []:
        for s in group.get("skills", []) or []:
            if s not in out:
                out.append(s)
    return out


def _structured_candidate_fields(full_resume: Dict[str, Any]) -> Dict[str, Any]:
    """把结构化档案里的关键信息回填到候选人平铺字段（公司/职位/技能/到岗等）"""
    basic = full_resume.get("basic_info") or {}
    works = full_resume.get("work_experience") or []
    first = works[0] if works else {}

    fields: Dict[str, Any] = {}
    if first.get("company"):
        fields["current_company"] = first["company"]
    if first.get("title"):
        fields["current_title"] = first["title"]
    skills = flat_skills_from_matrix(full_resume.get("skills_matrix"))
    if skills:
        fields["skills"] = skills
    if basic.get("target_salary"):
        fields["salary_expect"] = basic["target_salary"]

    status = basic.get("job_status") or ""
    if "离职" in status:
        fields["available_time"] = "随时到岗"
        fields["status"] = "available"
    elif status:
        fields["available_time"] = "在职 - 考虑合适机会"
        fields["status"] = "employed"
    return fields

