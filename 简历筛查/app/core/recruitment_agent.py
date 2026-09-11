"""
RecruitAI 资深招聘尽调智能体 (RecruitmentAgent)
实现完整的 ReAct 状态机循环（感知 Perceive → 规划 Plan → 行动 Act → 反思纠偏 Reflect）
具备履历测谎、技术资产外部探查、水分剥离与靶向面试题定制能力
"""
import copy
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.core.agent_tools import (
    timeline_cross_auditor,
    external_asset_probe,
    project_substance_evaluator,
    killer_question_generator,
)
from app.core.llm_client import generate_chat

logger = logging.getLogger(__name__)


class RecruitmentAgent:
    """
    资深技术招聘尽调 Agent
    """

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.max_tool_rounds = int(cfg.get("agent_max_tool_rounds", 3))

    async def run_deep_screening(
        self,
        resume_text: str,
        job: Dict[str, Any],
        hard_gate_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        运行 ReAct 尽调循环，产出带深度调查证据链的结构化评定档案
        """
        investigation_trace: List[str] = []
        risk_warnings: List[str] = []
        verified_highlights: List[str] = []
        targeted_interview_focus: List[str] = []

        # =====================================================================
        # 阶段 1: 感知 (Perceive)
        # =====================================================================
        truncated_resume = resume_text[:3500]
        investigation_trace.append("【阶段 1: 感知 (Perceive)】解析候选人履历特征与目标岗位JD契合点，初始化尽调任务...")

        # =====================================================================
        # 阶段 2: 规划 (Plan)
        # =====================================================================
        has_url_hint = any(k in resume_text.lower() for k in ["github.com", "gitee.com", "http", "blog", "juejin", "csdn"])
        plan_desc = [
            "1. 启动 timeline_cross_auditor 进行受教育与工作起止时间自洽性测谎",
            "2. 启动 external_asset_probe 探查公开开源项目与技术博客含金量" if has_url_hint else "2. 检索外链技术资产（若无则记录空档）",
            "3. 启动 project_substance_evaluator 过滤模糊动词，核查硬核架构指标与真实产出",
        ]
        investigation_trace.append(f"【阶段 2: 规划 (Plan)】制定多维尽调路径：\n  - " + "\n  - ".join(plan_desc))

        # =====================================================================
        # 阶段 3: 行动 (Act) - 调用工具箱取证
        # =====================================================================
        investigation_trace.append("【阶段 3: 行动 (Act)】依序调用工具箱开展多点交叉取证...")

        # 工具 1：时间线审计
        t_result = timeline_cross_auditor(resume_text)
        if not t_result["passed"]:
            for f in t_result["flags"]:
                risk_warnings.append(f"⚠️ 时间线可疑：{f}")
                investigation_trace.append(f"  ⚡ 工具反馈 [时间线测谎告警]: {f}")
        else:
            verified_highlights.append("✓ 履历时间线自洽：起止时间与教育背景衔接严密，未见明显断档")
            investigation_trace.append("  ✓ 工具反馈 [时间线自洽]: 各段经历时间衔接自然，逻辑合理")

        # 工具 2：外链资产探查
        e_result = external_asset_probe(resume_text)
        if e_result["has_links"]:
            for link in e_result["links_found"]:
                investigation_trace.append(f"  🔍 工具反馈 [外链资产扫描]: 发现公开技术地址 {link}")
            if e_result["risk_level"] == "medium":
                risk_warnings.append("⚠️ 外链资产存疑：开源仓库命名偏向练习或教学Demo，自研生产度存疑")
                investigation_trace.append("  ⚡ 工具反馈 [代码资产评定]: 仓库可能为简单学习练习，需在面试中重点核验")
            else:
                verified_highlights.append("✓ 技术自驱力核实：附带真实开源项目或技术主页，具备独立研发探索意愿")
                investigation_trace.append("  ✓ 工具反馈 [代码资产评定]: 附带真实技术资产，代码自研度良好")
        else:
            investigation_trace.append("  ℹ️ 工具反馈 [外链探查]: 简历未披露公开代码仓库")

        # 工具 3：项目含金量与划水判定
        p_result = project_substance_evaluator(resume_text, job.get("jd", ""))
        for b in p_result["buzzword_flags"]:
            risk_warnings.append(f"⚠️ 项目水分警示：{b}")
            investigation_trace.append(f"  ⚡ 工具反馈 [含金量分析]: {b}")
        for v in p_result["verified_strengths"]:
            verified_highlights.append(f"✓ 架构深度核实：{v}")
            investigation_trace.append(f"  ✓ 工具反馈 [含金量分析]: {v}")

        # 规则生成的兜底面试题
        fallback_questions = killer_question_generator(resume_text, t_result["flags"] + p_result["buzzword_flags"], job)

        # =====================================================================
        # 阶段 4: 反思与校准 (Reflect & Calibrate)
        # =====================================================================
        investigation_trace.append("【阶段 4: 反思与校准 (Reflect)】将全部取证物料注入大模型，启动深度反思与评级修正...")

        tool_evidence_summary = (
            f"- 时间线自洽性状态: {'通过' if t_result['passed'] else '异常告警'}\n"
            f"- 时间线疑点: {'; '.join(t_result['flags']) if t_result['flags'] else '无'}\n"
            f"- 外链技术资产: {'; '.join(e_result['findings'])}\n"
            f"- 项目含金量评分: {p_result['substance_score']} 分\n"
            f"- 项目可疑虚词与缺陷: {'; '.join(p_result['buzzword_flags']) if p_result['buzzword_flags'] else '无'}\n"
            f"- 真实架构突破点: {'; '.join(p_result['verified_strengths']) if p_result['verified_strengths'] else '常规业务开发'}"
        )

        system_prompt = (
            "你是一位严谨苛刻、具备深厚技术背景的资深技术招聘架构师与背调专家（Recruitment Agent）。"
            "你绝不轻易相信简历中的华丽辞藻，而是依据工具客观取证结果，对候选人的真实能力进行批判性反思与评定。"
            "必须严格输出合法 JSON 格式，不得包含任何 Markdown 标记或多余说明。"
        )

        prompt = f"""请基于以下岗位要求、候选人简历以及行动层工具箱客观取证物料，进行自主反思与最终定案：

【目标岗位需求 (JD)】
- 岗位名称: {job.get('title', '')}
- 薪资范围: {job.get('salary', '')}
- 工作经验: {job.get('experience_years', 0)} 年
- 学历要求: {job.get('education', 'any')} ({job.get('school_tier', 'any')})
- 核心技术栈: {', '.join(job.get('required_skills', []))}
- 岗位描述: {job.get('jd', '')}

【候选人简历原文 (节选)】
{truncated_resume}

【客观取证与侦测物料】
{tool_evidence_summary}

【反思与定案原则】
1. 真实度纠偏：若发现时间线倒挂、项目虚词密集或开源仅为教学Demo，必须在反思评语中严厉指出，并主动调低“技术深度”与“综合得分”；
2. 亮点实锤：若有真实高并发指标或硬核自研架构，给予充分肯定；
3. 面试针对性：量身定制 3 道具有“攻防测谎性质”的高质量技术面试题，直击其简历可疑点或最核心项目。

【严格以合法 JSON 输出】：
{{
  "score": 85,
  "tier": "A",
  "label": "A级·建议录用",
  "ai_reason": "综合深入反思评语（150-250字，必须结合取证结果，分析其优势与真实性风险）",
  "radar": {{
    "技术深度": 85,
    "项目规模": 80,
    "技术栈匹配": 90,
    "学历背景": 88,
    "发展潜力": 85
  }},
  "tags": ["✓ 5年资历·契合度高", "⚠️ 开源仓库可能为Demo练习", "✓ 掌握微前端架构"],
  "interview_questions": [
    "针对其可疑点或真实技术难点的测谎级面试题1",
    "针对其核心技术栈的攻防面试题2",
    "针对其工程稳定性的场景面试题3"
  ],
  "agent_reflection": "Agent自我反思轨迹记录（阐明如何依据证据推翻或确认候选人真实水平）",
  "targeted_interview_focus": [
    "面试需重点考察的核心破绽或架构要点1",
    "面试需核验的项目真实性要点2"
  ]
}}
"""

        try:
            raw_resp = await generate_chat(prompt, system_prompt=system_prompt, cfg=self.cfg, json_mode=True)
            cleaned = raw_resp.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()
            m = re.search(r"(\{.*\})", cleaned, re.DOTALL)
            if m:
                cleaned = m.group(1)
            
            eval_data = json.loads(cleaned)

            raw_score = eval_data.get("score", 50)
            try:
                score = int(raw_score)
            except Exception:
                score = 50

            # 统一按 score 重新规整 tier
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

            radar = eval_data.get("radar", {})
            if not isinstance(radar, dict):
                radar = {"技术深度": score, "项目规模": score, "技术栈匹配": score, "学历背景": score, "发展潜力": score}

            tags = eval_data.get("tags", [])
            if not isinstance(tags, list):
                tags = [str(tags)]

            questions = eval_data.get("interview_questions", [])
            if not isinstance(questions, list) or len(questions) == 0:
                questions = fallback_questions

            reflection = eval_data.get("agent_reflection", "")
            if reflection:
                investigation_trace.append(f"【反思定案结论】{reflection}")
            else:
                investigation_trace.append("【反思定案结论】综合时间线、代码资产与技术指标，形成客观公正的初筛定级。")

            targeted_focus = eval_data.get("targeted_interview_focus", [])
            if not isinstance(targeted_focus, list) or not targeted_focus:
                targeted_focus = [
                    "面试重点：核验其项目描述中量化指标的真实自研比例",
                    "面试重点：考察其在复杂架构异常情况下的现场推演与排障能力"
                ]

            return {
                "score": score,
                "tier": tier,
                "label": eval_data.get("label", f"{tier}级·尽调完成"),
                "ai_reason": eval_data.get("ai_reason", "深度尽调评估完成"),
                "radar": radar,
                "tags": tags,
                "interview_questions": questions,
                "deep_audit": {
                    "investigation_trace": investigation_trace,
                    "risk_warnings": risk_warnings,
                    "verified_highlights": verified_highlights,
                    "targeted_interview_focus": targeted_focus,
                }
            }

        except Exception as e:
            logger.warning(f"Agent 反思生成异常，启动降级保护: {e}")
            investigation_trace.append(f"【降级说明】大模型生成或解析遇到异常（{e}），启用工具层确定性取证保底交付。")
            
            # 即使大模型解析失败，工具层的真实取证绝不丢失！
            base_score = p_result["substance_score"]
            if not t_result["passed"]:
                base_score -= 15
            base_score = max(40, min(90, base_score))
            
            tier = "A" if base_score >= 80 else ("B" if base_score >= 70 else "C")
            
            return {
                "score": base_score,
                "tier": tier,
                "label": f"{tier}级·工具确定性初筛",
                "ai_reason": f"经自动化尽调工具箱取证：时间线自洽度{'良好' if t_result['passed'] else '存疑'}，工程含金量得分 {p_result['substance_score']} 分。建议面试官结合靶向问题深入核查。",
                "radar": {
                    "技术深度": base_score,
                    "项目规模": max(40, base_score - 5),
                    "技术栈匹配": base_score,
                    "学历背景": 80,
                    "发展潜力": base_score,
                },
                "tags": ["✓ 尽调工具已取证"] + [f"⚠️ {f}" for f in t_result["flags"][:2]],
                "interview_questions": fallback_questions,
                "deep_audit": {
                    "investigation_trace": investigation_trace,
                    "risk_warnings": risk_warnings,
                    "verified_highlights": verified_highlights,
                    "targeted_interview_focus": [
                        "建议重点核验其时间线断档或职位真实度",
                        "现场要求候选人手写微架构核心状态流转代码"
                    ],
                }
            }
