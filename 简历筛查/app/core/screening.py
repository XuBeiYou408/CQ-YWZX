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


def check_hard_gates(resume_text: str, job: Dict[str, Any]) -> Dict[str, Any]:
    """校验学历/院校/年限三项门槛，返回 {passed, fail_reasons, detected_edu, detected_school_tier, detected_exp_years}"""
    fail_reasons: List[str] = []

    detected_edu = _parse_edu_from_text(resume_text)
    detected_school_tier = _parse_school_tier_from_text(resume_text)
    detected_exp_years = _parse_experience_years_from_text(resume_text)

    # 1. 学历要求
    req_edu = job.get("education", "any").lower()
    req_edu_rank = EDU_RANK.get(req_edu, 0)
    det_edu_rank = EDU_RANK.get(detected_edu, 0)
    if det_edu_rank < req_edu_rank:
        edu_names = {"doctor": "博士", "master": "硕士", "bachelor": "本科", "associate": "大专"}
        req_name = edu_names.get(req_edu, req_edu)
        det_name = edu_names.get(detected_edu, detected_edu)
        fail_reasons.append(f"学历未达到要求（岗位要求: {req_name}，实际推断为: {det_name}）")

    # 2. 院校层次要求
    req_tier = job.get("school_tier", "any").lower()
    req_tier_rank = SCHOOL_TIER_RANK.get(req_tier, 0)
    det_tier_rank = SCHOOL_TIER_RANK.get(detected_school_tier, 0)
    if det_tier_rank < req_tier_rank:
        fail_reasons.append(
            f"院校层次未达标（岗位要求: {req_tier.upper()}，实际推断为: {detected_school_tier.upper()}）"
        )

    # 3. 工作年限要求
    req_exp = job.get("experience_years", 0)
    if detected_exp_years < req_exp:
        fail_reasons.append(
            f"工作年限不足（岗位要求: {req_exp}年，实际提取为: {detected_exp_years}年）"
        )

    return {
        "passed": len(fail_reasons) == 0,
        "fail_reasons": fail_reasons,
        "detected_edu": detected_edu,
        "detected_school_tier": detected_school_tier,
        "detected_exp_years": detected_exp_years,
    }


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
