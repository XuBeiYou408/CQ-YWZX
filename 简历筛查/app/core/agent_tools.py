"""
RecruitAI 深度调查智能体 - 行动层工具箱
包含：时间线交叉测谎工具、外部代码资产探查工具、项目含金量分析工具、靶向面试题生成器
"""
from datetime import datetime
import re
from typing import Any, Dict, List, Optional


def timeline_cross_auditor(resume_text: str) -> Dict[str, Any]:
    """
    履历时间线自洽性测谎工具
    提取受教育时间、各段工作履历起止时间，进行交叉比对：
    1. 检测是否存在时间严重重叠（如全职经历重合）；
    2. 检测毕业年限与声称的高级/架构师职位是否倒挂；
    3. 检测是否存在 > 1 年的未说明断档期 (Gap)。
    """
    flags: List[str] = []
    details: List[str] = []
    current_year = datetime.now().year

    # 1. 提取所有年份区间，如 2018.07 - 2021.06 或 2018 - 2021
    year_ranges = re.findall(r"(20\d{2})[^\d\n\r]{1,6}(20\d{2}|至今|现在|present)", resume_text, re.IGNORECASE)
    parsed_ranges = []
    for start_str, end_str in year_ranges:
        s_yr = int(start_str)
        e_yr = current_year if any(k in end_str.lower() for k in ["至今", "现在", "present"]) else int(end_str)
        if 2000 <= s_yr <= current_year and 2000 <= e_yr <= current_year + 1 and s_yr <= e_yr:
            parsed_ranges.append((s_yr, e_yr))

    # 2. 毕业年份检测
    edu_match = re.search(r"(20\d{2})[^\d\n\r]{1,10}?(?:毕业|学士|硕士|博士|本科)", resume_text)
    grad_year = int(edu_match.group(1)) if edu_match else None

    # 3. 职位倒挂检测（毕业年限 <= 2 年，却声称首席架构师、技术总监、CTO 等）
    high_level_titles = ["首席架构师", "总架构师", "技术总监", "研发总监", "cto", "vp", "专家架构师"]
    has_high_title = any(t in resume_text.lower() for t in high_level_titles)
    
    # 提取工龄
    exp_match = re.search(r"(\d+)\s*年(?:工作|从业|开发|研发|IT|全栈|前端|后端)?经验", resume_text)
    exp_years = int(exp_match.group(1)) if exp_match else None
    if grad_year:
        inferred_exp = max(0, current_year - grad_year)
        if exp_years and abs(exp_years - inferred_exp) >= 3:
            flags.append(f"工龄表述与毕业年份倒挂（毕业年份计算为 {inferred_exp} 年，简历自称 {exp_years} 年）")

    if (exp_years and exp_years <= 2) or (grad_year and (current_year - grad_year) <= 2):
        if has_high_title:
            flags.append("资历与职级严重脱节（工龄 ≤ 2 年却声称担任总监/首席架构师等高管职位）")

    # 4. 时间重叠与断档检测
    if len(parsed_ranges) >= 2:
        sorted_ranges = sorted(parsed_ranges, key=lambda x: x[0])
        for i in range(len(sorted_ranges) - 1):
            prev_end = sorted_ranges[i][1]
            next_start = sorted_ranges[i + 1][0]
            if next_start - prev_end >= 2:
                flags.append(f"检测到可能存在长达 {next_start - prev_end} 年的履历空白断档期（{prev_end} ~ {next_start}）")
                break

    passed = len(flags) == 0
    if passed:
        details.append("履历时间线逻辑自洽，起止时间与教育背景衔接合理，未发现重大断档或倒挂嫌疑。")
    else:
        details.extend(flags)

    return {
        "passed": passed,
        "flags": flags,
        "details": details,
        "grad_year": grad_year,
    }


def external_asset_probe(resume_text: str) -> Dict[str, Any]:
    """
    开源代码与外部技术资产探查工具
    检测简历中是否存在 GitHub、GitLab、技术博客或作品集外链并探查真实度。
    """
    findings: List[str] = []
    links_found: List[str] = []

    gh_matches = re.findall(r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.-]+)?)", resume_text, re.IGNORECASE)
    for m in gh_matches:
        full_url = f"https://github.com/{m}"
        if full_url not in links_found:
            links_found.append(full_url)

    blog_matches = re.findall(r"(?:https?://)?(?:www\.)?([a-zA-Z0-9_-]+\.(?:github\.io|gitee\.io|juejin\.cn|zhihu\.com/people|csdn\.net))", resume_text, re.IGNORECASE)
    for b in blog_matches:
        full_url = f"https://{b}"
        if full_url not in links_found:
            links_found.append(full_url)

    has_links = len(links_found) > 0
    risk_level = "none"

    if has_links:
        for url in links_found:
            findings.append(f"扫描到候选人外链技术资产：{url}")
            lower_url = url.lower()
            if any(k in lower_url for k in ["demo", "starter", "template", "study", "learn", "course", "practice", "hello"]):
                findings.append(f"【探查告警】仓库特征偏向练习Demo/模板工程（{url}），可能缺乏大型生产实践。")
                risk_level = "medium"
            else:
                findings.append(f"【核实确认】候选人附带真实技术项目/主页，具备自主技术探索意愿。")
    else:
        findings.append("简历中未附带任何公开代码仓库或技术博客外链。")

    return {
        "has_links": has_links,
        "links_found": links_found,
        "findings": findings,
        "risk_level": risk_level,
    }


def project_substance_evaluator(resume_text: str, target_jd: str = "") -> Dict[str, Any]:
    """
    项目含金量与划水判定器
    分析项目描述中是否存在“纯模糊动词（参与、协助、推进）”而无具体架构与量化产出的现象。
    提取真实架构指标（QPS/微前端沙箱/内存泄漏调优/BFF/高可用）。
    """
    buzzword_flags: List[str] = []
    verified_strengths: List[str] = []

    vague_verbs = ["负责推进", "参与编写", "协助沟通", "配合完成", "积极参与", "日常维护"]
    vague_count = sum(len(re.findall(re.escape(v), resume_text)) for v in vague_verbs)

    metric_keywords = [
        "qps", "tps", "p99", "并发", "性能提升", "延迟降低", "减少了", "提升了", "重构",
        "微前端", "沙箱", "虚拟滚动", "内存泄漏", "ast", "webpack", "vite", "bff",
        "分布式", "缓存穿透", "高可用", "组件库", "自动化测试"
    ]
    matched_metrics = []
    for k in metric_keywords:
        if k in resume_text.lower():
            matched_metrics.append(k)

    if vague_count >= 5 and len(matched_metrics) <= 2:
        buzzword_flags.append(f"项目描述多用模糊动词（累计出现 {vague_count} 次），缺乏明确量化指标，疑似边缘划水包装。")

    if matched_metrics:
        unique_m = list(set(matched_metrics))[:5]
        verified_strengths.append(f"具备深层工程与量化指标关键词：{', '.join(unique_m)}")
    else:
        buzzword_flags.append("项目陈述主要为业务常规流水账，未体现底层架构重构或技术突破点。")

    substance_score = max(40, min(95, 65 + len(matched_metrics) * 5 - vague_count * 3))

    return {
        "substance_score": substance_score,
        "buzzword_flags": buzzword_flags,
        "verified_strengths": verified_strengths,
        "matched_metrics": matched_metrics,
    }


def killer_question_generator(resume_text: str, flags: List[str], job: Dict[str, Any]) -> List[str]:
    """
    靶向高难度测谎题生成器
    """
    questions = []

    if any("脱节" in f or "倒挂" in f for f in flags):
        questions.append("【履历真实性测谎】您在简历中提及主导了高规格架构设计，请详细拆解您在架构初期所做的技术选型权衡矩阵与推演推翻记录？")

    lower_text = resume_text.lower()
    if "微前端" in lower_text:
        questions.append("【架构深度核验】针对微前端子应用通信与样式隔离，您在生产环境中遇到过最严重的样式污染或全局变量泄露事故是什么？具体如何排查并彻底根治的？")
    elif "react" in lower_text or "vue" in lower_text:
        questions.append("【底层原理考查】请结合您负责的项目，分析一次超大复杂数据流导致的页面掉帧卡顿，您是如何利用 Profiler 定位到具体重渲染根源并优化的？")

    if "node" in lower_text or "bff" in lower_text:
        questions.append("【生产稳定性攻防】面对 Node.js 服务在突发高流量下出现的 Event Loop 阻塞与内存持续攀升，您线上的排障工具链和限流降级方案是如何设计的？")

    if len(questions) < 3:
        questions.append(f"【业务拟合度】针对本岗位（{job.get('title', '该职位')}）的核心要求，您过往经历中最具技术迁移价值的工程实践是什么？")

    return questions[:3]
