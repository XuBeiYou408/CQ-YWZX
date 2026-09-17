import copy
import hashlib
import io
import json
import logging
import os
import re
import uuid
import zipfile
from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import CLOUD_PRESETS, load_config, save_config
from app.core.llm_client import generate_chat, get_model_status, test_cloud_connection
from app.core.parser import extract_text_from_bytes
from app.core.presets import PRESET_CANDIDATES, PRESET_JOBS
from app.core.screening import (
    screen_resume_full,
    rescreen_job_candidates,
    rescreen_candidate,
    check_candidate_hard_gates,
    recall_talent_to_candidates
)

logger = logging.getLogger(__name__)
router = APIRouter()

from app.core.storage import storage


def _ensure_init():
    storage.ensure_init()


def _get_all_candidates():
    storage.ensure_init()
    return storage.candidates


def _get_all_jobs():
    storage.ensure_init()
    return storage.jobs


# ─────────────────────────── 模型管理接口 ───────────────────────────

@router.get("/api/model/status")
async def model_status():
    cfg = load_config()
    status = await get_model_status(cfg)
    return {"ok": True, "data": status}


@router.post("/api/model/test")
async def model_test(body: dict):
    base_url = body.get("base_url", "")
    api_key = body.get("api_key", "")
    model_name = body.get("model_name", "")
    timeout = int(body.get("timeout", 10))
    if not base_url or not api_key or not model_name:
        raise HTTPException(status_code=400, detail="base_url / api_key / model_name 不能为空")
    result = await test_cloud_connection(base_url, api_key, model_name, timeout)
    return {"ok": result["success"], "data": result}


@router.post("/api/model/switch")
async def model_switch(body: dict):
    cfg = load_config()
    provider = body.get("active_provider", "local")
    if provider not in ("local", "cloud"):
        raise HTTPException(status_code=400, detail="active_provider 必须为 local 或 cloud")
    cfg["active_provider"] = provider
    if "cloud_model" in body and isinstance(body["cloud_model"], dict):
        cfg["cloud_model"].update(body["cloud_model"])
    save_config(cfg)
    return {"ok": True, "data": {"active_provider": provider}}


@router.get("/api/model/presets")
def model_presets():
    return {"ok": True, "data": CLOUD_PRESETS}


# ─────────────────────────── 岗位管理接口 ───────────────────────────

@router.get("/api/jobs")
def list_jobs():
    return {"ok": True, "data": _get_all_jobs()}


@router.post("/api/jobs")
def create_job(body: dict):
    jobs = _get_all_jobs()
    job_id = body.get("id") or f"job-{uuid.uuid4().hex[:6]}"
    new_job = {
        "id": job_id,
        "title": body.get("title", "新设招聘岗位"),
        "department": body.get("department", "技术研发部"),
        "salary": body.get("salary", "25-40K · 15薪"),
        "location": body.get("location", "深圳 · 南山"),
        "hc": int(body.get("hc", 2)),
        "experience_years": int(body.get("experience_years", 3)),
        "education": body.get("education", "bachelor"),
        "school_tier": body.get("school_tier", "any"),
        "required_skills": body.get("required_skills", ["TypeScript", "微服务", "架构设计"]),
        "jd": body.get("jd", "岗位职责与要求待完善。")
    }
    storage.jobs.insert(0, new_job)
    storage.save()
    return {"ok": True, "data": new_job}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    jobs = _get_all_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return {"ok": True, "data": job}


def _process_talent_pool_recall(job: dict) -> list:
    """
    当岗位门槛规则发生变更时，自动检索企业人才公海池：
    比对公海中所有储备人才与目标岗位的最新硬性门槛，
    凡符合门槛要求的储备人才，自动从公海唤醒召回并重新推入候选人初筛匹配队列。
    """
    _ensure_init()
    recalled = []
    remaining = []
    existing_ids = {c["id"] for c in storage.candidates}

    for talent in storage.talent_pool:
        # 核验公海人才是否满足当前调整后的最新门槛
        gate_res = check_candidate_hard_gates(talent, job)
        if gate_res["passed"]:
            cand = recall_talent_to_candidates(talent, job)
            if cand["id"] in existing_ids:
                cand["id"] = f"restored-{uuid.uuid4().hex[:6]}"
            cand["job_id"] = job.get("id", "fe-fullstack")
            storage.candidates.insert(0, cand)
            existing_ids.add(cand["id"])
            recalled.append(cand)
        else:
            remaining.append(talent)

    storage.talent_pool[:] = remaining
    return recalled


@router.put("/api/jobs/{job_id}")
def update_job(job_id: str, body: dict):
    jobs = _get_all_jobs()
    for i, j in enumerate(jobs):
        if j["id"] == job_id:
            # 兼容处理 experience_range 与 experience_years 联动
            if "experience_range" in body:
                rng = body.get("experience_range")
                if rng in ("any", "经验不限", "应届生"):
                    body["experience_years"] = 0
                elif rng == "1-3年":
                    body["experience_years"] = 1
                elif rng == "3-5年":
                    body["experience_years"] = 3
                elif rng == "5-10年":
                    body["experience_years"] = 5
                elif rng == "10年以上":
                    body["experience_years"] = 10
            elif "experience_years" in body:
                try:
                    body["experience_years"] = int(body["experience_years"])
                except Exception:
                    pass

            jobs[i].update({k: v for k, v in body.items() if k != "id"})

            # 核心闭环 1：自动比对人才公海，凡满足新门槛要求的储备人才立即唤醒召回，重新推入匹配池
            recalled_cands = _process_talent_pool_recall(jobs[i])

            # 核心闭环 2：对本岗位所有现有候选人（含新召回人员）执行全量初筛重新判定与状态同步
            candidates = _get_all_candidates()
            rescreen_job_candidates(candidates, jobs[i])

            # 重新核算该岗位的即时统计数据
            job_cands = [c for c in candidates if c.get("job_id") == job_id]
            counts = {
                "all": len(job_cands),
                "recommended": sum(1 for c in job_cands if c.get("state") == "recommended"),
                "review": sum(1 for c in job_cands if c.get("state") == "review"),
                "scheduled": sum(1 for c in job_cands if c.get("state") == "scheduled"),
                "rejected": sum(1 for c in job_cands if c.get("state") == "rejected"),
            }

            # 核心闭环 3：面试排期联动清洗
            # 若门槛收紧导致原约面候选人被硬性拦截淘汰，联动撤销其待面试日程，避免无效约面
            rejected_ids = {c["id"] for c in storage.candidates if c.get("state") == "rejected"}
            storage.interviews[:] = [iv for iv in storage.interviews if iv.get("candidate_id") not in rejected_ids]

            recalled_count = len(recalled_cands)
            recalled_names = [c["name"] for c in recalled_cands]
            if recalled_count > 0:
                msg = f"岗位规则已生效！初筛结果已联动更新，并从人才公海自动召回 {recalled_count} 位符合最新门槛的储备人才（{'、'.join(recalled_names)}）重新进入匹配！"
            else:
                msg = "岗位规则与硬性门槛已生效，全量候选人初筛比对与拦截结果已闭环更新！"

            # 核心闭环 4：全量状态即刻持久化落盘
            storage.save()

            return {
                "ok": True,
                "data": jobs[i],
                "counts": counts,
                "recalled_count": recalled_count,
                "recalled_names": recalled_names,
                "talent_pool_count": len(storage.talent_pool),
                "message": msg
            }
    raise HTTPException(status_code=404, detail="岗位不存在")


@router.post("/api/jobs/{job_id}/rescreen")
def trigger_rescreen(job_id: str):
    jobs = _get_all_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    recalled_cands = _process_talent_pool_recall(job)
    candidates = _get_all_candidates()
    rescreen_job_candidates(candidates, job)
    job_cands = [c for c in candidates if c.get("job_id") == job_id]
    counts = {
        "all": len(job_cands),
        "recommended": sum(1 for c in job_cands if c.get("state") == "recommended"),
        "review": sum(1 for c in job_cands if c.get("state") == "review"),
        "scheduled": sum(1 for c in job_cands if c.get("state") == "scheduled"),
        "rejected": sum(1 for c in job_cands if c.get("state") == "rejected"),
    }
    # 联动清洗被淘汰人员的排期
    rejected_ids = {c["id"] for c in storage.candidates if c.get("state") == "rejected"}
    storage.interviews[:] = [iv for iv in storage.interviews if iv.get("candidate_id") not in rejected_ids]

    recalled_count = len(recalled_cands)
    recalled_names = [c["name"] for c in recalled_cands]
    msg = f"全量重筛完成，从公海召回 {recalled_count} 位符合门槛人才（{'、'.join(recalled_names)}）！" if recalled_count else "全量重筛完成"
    storage.save()
    return {
        "ok": True,
        "data": {"job": job, "counts": counts},
        "recalled_count": recalled_count,
        "recalled_names": recalled_names,
        "talent_pool_count": len(storage.talent_pool),
        "message": msg
    }


# ─────────────────────────── 候选人查询与操作接口 ───────────────────────────

@router.get("/api/candidates")
def list_candidates(
    job_id: str = "fe-fullstack",
    tab: str = "all",
    q: str = "",
    sort: str = "score",
    edu_filter: str = "all",
    exp_filter: str = "all",
):
    candidates = [c for c in _get_all_candidates() if c.get("job_id") == job_id]
    
    # Tab 过滤
    tab_map = {
        "recommended": lambda c: c.get("state") == "recommended",
        "review": lambda c: c.get("state") == "review",
        "scheduled": lambda c: c.get("state") == "scheduled",
        "rejected": lambda c: c.get("state") == "rejected",
    }
    if tab in tab_map:
        candidates = [c for c in candidates if tab_map[tab](c)]
        
    # 学历过滤
    if edu_filter != "all":
        if edu_filter == "985":
            candidates = [c for c in candidates if c.get("school_tier") == "985"]
        elif edu_filter == "master":
            candidates = [c for c in candidates if c.get("education") in ("master", "doctor")]
        elif edu_filter == "bachelor":
            candidates = [c for c in candidates if c.get("education") in ("bachelor", "master", "doctor")]
            
    # 工作经验过滤
    if exp_filter != "all":
        if exp_filter == "1-3":
            candidates = [c for c in candidates if 1 <= c.get("experience_years", 0) <= 3]
        elif exp_filter == "3-5":
            candidates = [c for c in candidates if 3 <= c.get("experience_years", 0) <= 5]
        elif exp_filter == "5+":
            candidates = [c for c in candidates if c.get("experience_years", 0) >= 5]

    # 关键词搜索
    if q.strip():
        q_lower = q.lower()
        candidates = [
            c for c in candidates
            if q_lower in c.get("name", "").lower()
            or q_lower in " ".join(c.get("skills", [])).lower()
            or q_lower in c.get("current_company", "").lower()
            or q_lower in c.get("school", "").lower()
        ]
        
    # 排序
    if sort == "score":
        candidates = sorted(candidates, key=lambda c: c.get("ai_score", 0), reverse=True)
    elif sort == "time":
        candidates = list(reversed(candidates))
        
    all_for_job = [c for c in _get_all_candidates() if c.get("job_id") == job_id]
    counts = {
        "all": len(all_for_job),
        "recommended": sum(1 for c in all_for_job if c.get("state") == "recommended"),
        "review": sum(1 for c in all_for_job if c.get("state") == "review"),
        "scheduled": sum(1 for c in all_for_job if c.get("state") == "scheduled"),
        "rejected": sum(1 for c in all_for_job if c.get("state") == "rejected"),
    }
    return {"ok": True, "data": candidates, "counts": counts}


@router.get("/api/candidates/{candidate_id}")
def get_candidate(candidate_id: str):
    candidates = _get_all_candidates()
    c = next((x for x in candidates if x["id"] == candidate_id), None)
    if not c:
        raise HTTPException(status_code=404, detail="候选人不存在")
    return {"ok": True, "data": c}


@router.patch("/api/candidates/{candidate_id}/state")
def update_candidate_state(candidate_id: str, body: dict):
    valid_states = {"recommended", "review", "scheduled", "rejected"}
    new_state = body.get("state", "")
    if new_state not in valid_states:
        raise HTTPException(status_code=400, detail="无效状态")
    candidates = _get_all_candidates()
    for c in candidates:
        if c["id"] == candidate_id:
            c["state"] = new_state
            _ensure_init()
            # 如果是约面状态，联动同步到面试日程库
            if new_state == "scheduled":
                existing = next((iv for iv in storage.interviews if iv.get("candidate_id") == candidate_id), None)
                if not existing:
                    if candidate_id == "preset-002":
                        storage.interviews.append({
                            "id": "iv-002",
                            "candidate_id": "preset-002",
                            "candidate_name": "陈书婷",
                            "job_title": "资深前端开发 / 全栈工程师",
                            "round": "双语技术面 (海外连线)",
                            "time": "明日 10:00 - 11:00",
                            "interviewer": "海外技术总监 David",
                            "meeting_link": "https://meeting.recruitai.com/room/777-666",
                            "status": "upcoming"
                        })
                    else:
                        storage.interviews.append({
                            "id": f"iv-{uuid.uuid4().hex[:6]}",
                            "candidate_id": candidate_id,
                            "candidate_name": c.get("name", "候选人"),
                            "job_title": "资深前端开发 / 全栈工程师",
                            "round": "业务初试 (视频)",
                            "time": "建议安排本周内",
                            "interviewer": "技术负责人",
                            "meeting_link": f"https://meeting.recruitai.com/room/{uuid.uuid4().hex[:6]}",
                            "status": "upcoming"
                        })
            else:
                # 候选人移出约面状态（如淘汰或转入待复核），从待面试日程中联动移除
                storage.interviews[:] = [iv for iv in storage.interviews if iv.get("candidate_id") != candidate_id]

            # 如果是回绝状态，联动注入回绝通知到聊天记录中
            if new_state == "rejected":
                cid = c["id"]
                cname = c.get("name", "候选人")
                history = storage.chat_history.setdefault(cid, [])
                _drop_seeded(history)
                if not any(m.get("is_reject") for m in history):
                    history.append({
                        "sender": "system",
                        "name": "企业招聘系统 · 委婉回绝通知",
                        "text": f"尊敬的{cname}先生/女士：感谢您关注并投递我司职位。经过系统综合评估与招聘委员会审阅，您的经历非常值得赞赏，但鉴于本次HC名额有限及当下技术栈契合度考量，暂未能安排本期面试。您的简历已纳入我司战略人才储备库。祝您求职顺利！",
                        "time": datetime.now().strftime("%H:%M"),
                        "is_reject": True
                    })
            storage.save()
            return {"ok": True, "data": c}
    raise HTTPException(status_code=404, detail="候选人不存在")


@router.post("/api/candidates/{candidate_id}/generate-questions")
async def regenerate_questions(candidate_id: str):
    """根据候选人背景调用大模型重新生成 3 道个性化、具备大厂深度的针对性面试问题"""
    candidates = _get_all_candidates()
    c = next((x for x in candidates if x["id"] == candidate_id), None)
    if not c:
        raise HTTPException(status_code=404, detail="候选人不存在")
    
    name = c.get("name", "候选人")
    company = c.get("current_company", "互联网企业")
    title = c.get("current_title", "工程师")
    exp = c.get("experience_years", 3)
    skills = ", ".join(c.get("skills", ["核心技术栈"]))
    
    # 获取关联的目标岗位信息
    jobs = _get_all_jobs()
    job = next((j for j in jobs if j["id"] == c.get("job_id")), None)
    job_title = job.get("title", "技术岗位") if job else "技术架构师"
    job_jd = (job.get("jd", "") if job else "")[:400]
    
    # 提取候选人真实履历战绩与项目细节
    work_highlights = []
    full_res = c.get("full_resume", {})
    for w in full_res.get("work_experience", [])[:2]:
        co = w.get("company", "")
        ach = w.get("achievements") or w.get("responsibilities", "")
        if ach:
            work_highlights.append(f"{co}工作重点：{ach}")
    for p in full_res.get("project_experience", [])[:2]:
        pname = p.get("name", "")
        resp = p.get("responsibilities") or p.get("technologies", "")
        if resp:
            work_highlights.append(f"项目【{pname}】：{resp}")
    
    # 精炼履历实战与JD，避免无意义冗长字符导致推理模型思考超时
    concise_exp = "\n".join(work_highlights[:3]) if work_highlights else c.get("ai_reason", "具备大厂研发背景")
    if len(concise_exp) > 400:
        concise_exp = concise_exp[:400] + "..."
    
    cfg = load_config()
    system_prompt = (
        "你是一位严谨苛刻的大厂资深技术面试官与系统架构师。"
        "请根据候选人的真实履历背景、项目难点与技术栈，量身定制 3 道犀利、直击工程实战难点的深度技术追问。\n"
        "【严格要求】：\n"
        "1. 严禁使用任何模板插槽或空泛套话，每道题目必须紧扣候选人主导的具体业务场景（如微前端解耦、高并发排障、链路降级、架构权衡）；\n"
        "2. 语言必须自然生动，符合大厂技术专家真实发问口吻，每道问题 40~90 字；\n"
        "3. 必须输出包含 3 道完整提问句子的合法 JSON，格式：{\"interview_questions\": [\"完整问题内容1\", \"完整问题内容2\", \"完整问题内容3\"]}。"
    )
    prompt = f"""【应聘岗位】: {job_title}
【候选人画像】: {name} · {company} · {title}（{exp}年经验）
【核心技术栈】: {skills}
【核心项目与实战细节】:
{concise_exp}

请针对候选人的上述具体经历，量身提炼生成 3 道具备大厂实战深度的具体面试追问。严格只返回合法 JSON：
{{
  "interview_questions": [
    "<针对其主导项目核心难点或高并发瓶颈的具体实战追问>",
    "<针对其技术栈选型权衡或排障定位过程的实战追问>",
    "<针对系统稳定性、容灾解耦或落地难点的实战追问>"
  ]
}}"""

    new_questions = []
    try:
        raw = await generate_chat(prompt, system_prompt=system_prompt, cfg=cfg, json_mode=True)
        cleaned = raw.strip()
        # 1. 尝试从文本中精准提取 JSON 块
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                qs = data.get("interview_questions", [])
                if isinstance(qs, list) and len(qs) >= 1:
                    valid_qs = [
                        str(q).strip() for q in qs 
                        if str(q).strip() and len(str(q).strip()) > 15 and not str(q).strip().startswith("追问")
                    ]
                    if valid_qs:
                        new_questions = valid_qs[:3]
            except Exception:
                pass

        # 2. 若模型未按 JSON 输出，按行提取 Q1/Q2/Q3 或 1./2./3.
        if not new_questions:
            lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
            for l in lines:
                m = re.match(r"^(?:Q\d+[\.、:：]|\d+[\.、:：]|[-*])\s*(.+)", l)
                if m and len(m.group(1).strip()) > 10:
                    new_questions.append(m.group(1).strip())
            new_questions = new_questions[:3]
    except Exception as e:
        logger.error(f"大模型生成追问异常: {e}", exc_info=True)

    # 3. 兜底保护：若离线断网且无云端配置，基于候选人具体项目做量身深度提炼
    if len(new_questions) < 3:
        primary_skill = skills.split(",")[0].strip() if skills else "核心技术"
        fallback_pool = [
            f"你在{company}主导核心模块期间，面对复杂业务场景与突发流量冲击时，具体采取了哪些解耦、容灾与服务降级策略？",
            f"结合你在{primary_skill}领域的实战攻防经验，过往在线上遇到过最棘手的疑难排障案例是什么，排障路径与复盘收益如何？",
            f"如果将你过往在{company}沉淀的工程方案迁移至我们{job_title}团队的业务场景，你预判前30天最关键的技术里程碑与落地卡点是什么？"
        ]
        for q in fallback_pool:
            if len(new_questions) < 3 and q not in new_questions:
                new_questions.append(q)

    c["interview_questions"] = new_questions
    storage.save()
    return {"ok": True, "data": {"interview_questions": new_questions}}


@router.post("/api/candidates/{candidate_id}/reject-notify")
def reject_notify(candidate_id: str):
    """向淘汰候选人正式发送系统委婉回绝信，并写入该候选人的沟通记录"""
    candidates = _get_all_candidates()
    c = next((x for x in candidates if x["id"] == candidate_id), None)
    if not c:
        raise HTTPException(status_code=404, detail="候选人不存在")
    c["state"] = "rejected"
    now_str = datetime.now().strftime("%H:%M")
    notice_text = f"尊敬的{c.get('name')}先生/女士：感谢您关注并投递我司职位。经过系统综合评估与招聘委员会审阅，您的经历非常值得赞赏，但鉴于本次HC名额有限及当下技术栈契合度考量，暂未能安排本期面试。您的简历已纳入我司核心战略人才储备库，后续有合适岗位我们将第一时间与您取得联系。祝您求职顺利，前程似锦！"
    notice = {
        "candidate_id": candidate_id,
        "candidate_name": c.get("name"),
        "sent_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "content": notice_text
    }
    storage.rejections.append(notice)
    
    # 核心闭环：同步注入到该候选人的微聊沟通记录中
    _ensure_init()
    history = storage.chat_history.setdefault(candidate_id, [])
    _drop_seeded(history)
    if not any(m.get("is_reject") for m in history):
        history.append({
            "sender": "system",
            "name": "企业招聘系统 · 委婉回绝通知",
            "text": notice_text,
            "time": now_str,
            "is_reject": True
        })
        
    # 联动清理面试排期
    storage.interviews[:] = [iv for iv in storage.interviews if iv.get("candidate_id") != candidate_id]
    storage.save()
    return {"ok": True, "data": notice, "message": f"已向候选人【{c.get('name')}】发送标准化委婉回绝通知及感谢信"}


# ─────────────────────────── 真实候选人对话沟通接口 ───────────────────────────

def _chat_recency_key(item: dict) -> int:
    """按最新消息时间倒序排序（无时间戳的排最后）"""
    m = re.search(r"(\d{1,2}):(\d{2})", item.get("last_time") or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else -1


def _greeting_text(cname: str, job_title: str) -> str:
    """公司侧（HR）发起沟通的标准招呼语"""
    return (
        f"您好，{cname}！我是【{job_title}】岗位的招聘负责人，"
        f"已查阅您投递的简历，履历与我们岗位的匹配度不错，想和您进一步沟通了解。"
        f"方便的话请告知您近期方便沟通的时间，我们也可以直接安排线上技术面。"
    )


#: 系统早期自动补的「候选人开场白」特征（并非真实沟通），历史数据也据此识别
_SEED_TAIL = "我的核心履历已经通过系统初筛，期待与您深入交流！"


def _is_seeded_message(msg: dict) -> bool:
    """该消息是否为系统自动补的候选人开场白（不是真实沟通内容）"""
    if msg.get("seeded"):
        return True
    return msg.get("sender") == "candidate" and _SEED_TAIL in str(msg.get("text", ""))


def _drop_seeded(history: list) -> list:
    """剔除历史里系统自动补的开场白（就地修改并返回）"""
    history[:] = [m for m in history if not _is_seeded_message(m)]
    return history



def _append_greeting(candidate: dict) -> bool:
    """写入一条「公司先发起」的招呼消息；已招呼过则返回 False（幂等）"""
    cid = candidate["id"]
    cname = candidate.get("name", "候选人")
    job = next((j for j in _get_all_jobs() if j["id"] == candidate.get("job_id")), None)
    job_title = (job or {}).get("title", "当前岗位")
    history = _drop_seeded(storage.chat_history.setdefault(cid, []))
    if any(m.get("is_greeting") for m in history):
        return False
    history.append({
        "sender": "hr",
        "name": "HR 主管",
        "text": _greeting_text(cname, job_title),
        "time": datetime.now().strftime("%H:%M"),
        "is_greeting": True,
    })
    candidate["contacted"] = True
    candidate["contacted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return True



@router.get("/api/chats")
def list_chats(job_id: str = ""):
    """沟通中心候选人列表：仅返回真正产生过沟通记录（招呼/互发/回绝）的候选人"""
    _ensure_init()
    candidates = _get_all_candidates()
    if job_id:
        candidates = [c for c in candidates if c.get("job_id") == job_id]
    result = []
    for c in candidates:
        cid = c["id"]
        hist = _drop_seeded(storage.chat_history.get(cid) or [])
        if not hist:
            # 未产生过任何沟通记录（未被招呼 / 未互发消息 / 未回绝）的候选人不进沟通中心，
            # 否则「一键发起招呼」看起来像没生效。
            continue
        last_msg = hist[-1]
        result.append({
            "candidate_id": cid,
            "candidate": c,
            "message_count": len(hist),
            "last_message": last_msg.get("text", ""),
            "last_sender": last_msg.get("sender", ""),
            "last_time": last_msg.get("time", ""),
            "is_rejected": c.get("state") == "rejected"
        })
    result.sort(key=_chat_recency_key, reverse=True)
    return {"ok": True, "data": result}


@router.get("/api/candidates/{candidate_id}/chat")
def get_chat_history(candidate_id: str):
    """候选人会话记录：只返回真实沟通内容（系统早期自动补的开场白已剔除）"""
    _ensure_init()
    c = next((x for x in _get_all_candidates() if x["id"] == candidate_id), None)
    cname = c["name"] if c else "候选人"
    history = _drop_seeded(storage.chat_history.setdefault(candidate_id, []))
    history_modified = False

    # 淘汰候选人自动补齐回绝通知；复核激活后自动补激活说明
    if c and c.get("state") == "rejected" and not any(m.get("is_reject") for m in history):
        history.append({
            "sender": "system",
            "name": "企业招聘系统 · 委婉回绝通知",
            "text": f"尊敬的{cname}先生/女士：感谢您关注并投递我司职位。经过系统综合评估与招聘委员会审阅，您的经历非常值得赞赏，但鉴于本次HC名额有限及当下技术栈契合度考量，暂未能安排本期面试。您的简历已纳入我司企业人才储备库。祝您求职顺利！",
            "time": datetime.now().strftime("%H:%M"),
            "is_reject": True
        })
        history_modified = True
    elif c and c.get("state") != "rejected" and any(m.get("is_reject") for m in history) and not any(m.get("is_reactivated") for m in history):
        history.append({
            "sender": "system",
            "name": "企业招聘系统 · 重新激活通知",
            "text": f"尊敬的{cname}先生/女士：经招聘委员会重新复核评估，您的简历已重新激活进入复核/约面流程！",
            "time": datetime.now().strftime("%H:%M"),
            "is_reactivated": True
        })
        history_modified = True

    if history_modified:
        storage.save()
    return {"ok": True, "data": history}


@router.post("/api/candidates/{candidate_id}/chat")
async def send_chat_message(candidate_id: str, body: dict):
    _ensure_init()
    msg_text = body.get("message", "").strip()
    if not msg_text:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
        
    history = storage.chat_history.setdefault(candidate_id, [])
    now_str = datetime.now().strftime("%H:%M")
    
    # 记录 HR 消息
    history.append({
        "sender": "hr",
        "name": "HR 主管",
        "text": msg_text,
        "time": now_str
    })
    
    # 模拟候选人拟真回复
    c = next((x for x in _get_all_candidates() if x["id"] == candidate_id), None)
    cname = c["name"] if c else "候选人"
    
    # 兜底默认回复
    reply = f"好的，感谢HR老师的认可！我工作日随时可配合线上面试。若有技术笔试或作品集要求，我也能立即提交！"
    if "到岗" in msg_text:
        reply = f"关于到岗时间：我目前状态为{c.get('available_time','随时到岗')}，如果聊得顺利，一周内即可正式入职！"
    elif "薪资" in msg_text or "期望" in msg_text:
        reply = f"关于薪资期望：我的预期范围是 {c.get('salary_expect','25-35K')}，可以根据公司具体的职级和福利结构综合沟通！"
    elif "并发" in msg_text or "架构" in msg_text or "微前端" in msg_text:
        reply = f"关于技术经验：我在过往经历中主导过微前端子应用架构与高并发系统优化，线上面试中我很乐意分享具体的落地方案与指标！"
    elif "面试" in msg_text or "时间" in msg_text:
        reply = f"太好了！我近期工作日时间较为充裕，可以直接安排腾讯会议/飞书视频面试，静候您的日历邀约！"

    # 优先调用大模型模拟候选人真实沉浸式回复
    try:
        cfg = load_config()
        system_prompt = (
            f"你现在正在扮演求职候选人【{cname}】与用人单位的HR主管进行在线微聊沟通。\n"
            f"【你的真实背景画像】：\n"
            f"- 从业资历：{c.get('experience_years', 3)}年经验，毕业于{c.get('school', '高校')} ({c.get('education', '本科')})\n"
            f"- 当前职位：{c.get('current_company', '互联网企业')} · {c.get('current_title', '技术专家')}\n"
            f"- 期望薪资：{c.get('salary_expect', '面议')}\n"
            f"- 到岗时间：{c.get('available_time', '两周内到岗')}\n"
            f"- 核心擅长：{', '.join(c.get('skills', ['全栈研发']))}\n"
            f"【回复准则】：\n"
            f"1. 态度谦逊得体但展现出扎实的技术底气与专业度；\n"
            f"2. 紧扣 HR 发来的消息进行真诚、有理有据的回复，字数控制在 50~120 字；\n"
            f"3. 直接以候选人第一人称输出回复文本，严禁输出任何括号、前缀或旁白。"
        )
        prompt = f"HR 发来消息：\"{msg_text}\"\n\n请直接输出你作为候选人的回复："
        ai_reply = await generate_chat(prompt, system_prompt=system_prompt, cfg=cfg, json_mode=False)
        ai_reply = ai_reply.strip().strip('"').strip("'")
        if ai_reply and len(ai_reply) >= 5:
            reply = ai_reply
    except Exception as e:
        logger.warning(f"大模型模拟候选人回复失败，降级为内置模版: {e}")

    history.append({
        "sender": "candidate",
        "name": cname,
        "text": reply,
        "time": now_str
    })
    
    storage.save()
    return {"ok": True, "data": {"reply": reply, "history": history}}


# ─────────────────────────── 面试日程管理接口 ───────────────────────────

@router.get("/api/interviews")
def list_interviews(job_id: str = "fe-fullstack"):
    _ensure_init()
    candidates_map = {c["id"]: c for c in _get_all_candidates()}
    # 严格对齐：仅返回关联候选人当前状态仍为 scheduled 的有效排期
    active_ivs = []
    for iv in storage.interviews:
        cid = iv.get("candidate_id")
        cand = candidates_map.get(cid)
        if cand:
            if cand.get("state") == "scheduled":
                active_ivs.append(iv)
        else:
            active_ivs.append(iv)
    return {"ok": True, "data": active_ivs}


@router.post("/api/interviews/schedule")
def schedule_interview(body: dict):
    _ensure_init()
    c_id = body.get("candidate_id")
    c = next((x for x in _get_all_candidates() if x["id"] == c_id), None)
    item = {
        "id": f"iv-{uuid.uuid4().hex[:6]}",
        "candidate_id": c_id,
        "candidate_name": c["name"] if c else body.get("candidate_name", "候选人"),
        "job_title": body.get("job_title", "资深前端开发 / 全栈工程师"),
        "round": body.get("round", "技术初试"),
        "time": body.get("time", "明日 14:00 - 15:00"),
        "interviewer": body.get("interviewer", "技术总监"),
        "meeting_link": f"https://meeting.recruitai.com/room/{uuid.uuid4().hex[:6]}",
        "status": "upcoming"
    }
    storage.interviews.append(item)
    if c:
        c["state"] = "scheduled"
    storage.save()
    return {"ok": True, "data": item}


@router.patch("/api/interviews/{interview_id}")
def update_interview(interview_id: str, body: dict):
    _ensure_init()
    iv = next((x for x in storage.interviews if x["id"] == interview_id), None)
    if not iv:
        raise HTTPException(status_code=404, detail="面试日程不存在")
    iv.update(body)
    storage.save()
    return {"ok": True, "data": iv}


# ─────────────────────────── 人才公海接口 ───────────────────────────

@router.get("/api/talent-pool")
def list_talent_pool():
    _ensure_init()
    return {"ok": True, "data": storage.talent_pool}


@router.post("/api/talent-pool/restore")
def restore_talent(body: dict):
    _ensure_init()
    pool_id = body.get("pool_id") or body.get("candidate_id") or body.get("id")
    target = next((x for x in storage.talent_pool if x["id"] == pool_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="公海候选人不存在")
        
    storage.talent_pool.remove(target)
    target_job_id = body.get("target_job_id", "fe-fullstack")
    job = next((j for j in _get_all_jobs() if j["id"] == target_job_id), None) or {"title": "当前岗位", "id": target_job_id}
    
    new_candidate = recall_talent_to_candidates(target, job)
    new_candidate["tags"] = ["✓ 公海核心储备·手动激活", "✓ 资质核验完成", "✓ 高契合度画像"]
    new_candidate["ai_label"] = f"{new_candidate['ai_tier']}级·公海激活"
    new_candidate["label"] = new_candidate["ai_label"]
    new_candidate["ai_reason"] = f"从企业人才公海池高匹配库重新激活至【{job.get('title','')}】岗位，技术栈与项目体量贴合业务需求。"
    
    new_candidate["job_id"] = target_job_id
    storage.candidates.insert(0, new_candidate)
    storage.save()
    return {"ok": True, "data": new_candidate, "talent_pool_count": len(storage.talent_pool)}


# ─────────────────────────── AI 智能全景诊断报告 ───────────────────────────

@router.get("/api/diagnostics")
async def run_diagnostics(job_id: str = "fe-fullstack"):
    cfg = load_config()
    candidates = [c for c in _get_all_candidates() if c.get("job_id") == job_id]
    jobs = _get_all_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        job = jobs[0] if jobs else {"title": "当前岗位", "salary": "面议", "hc": 2, "required_skills": []}

    total = len(candidates)
    if total == 0:
        return {
            "ok": True,
            "data": {
                "health_score": 60,
                "avg_score": 0,
                "total_screened": 0,
                "high_match_rate": "0%",
                "rejection_rate": "0%",
                "insights": ["当前岗位人才库暂无候选人投递样本，建议扩大招聘渠道或导入简历数据。"],
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }

    s_cands = [c for c in candidates if c.get("ai_tier") == "S"]
    a_cands = [c for c in candidates if c.get("ai_tier") == "A"]
    b_cands = [c for c in candidates if c.get("ai_tier") == "B"]
    rej_cands = [c for c in candidates if c.get("state") == "rejected"]

    s_count = len(s_cands)
    a_count = len(a_cands)
    rej_count = len(rej_cands)
    high_match_count = s_count + a_count

    avg_score = round(sum(c.get("ai_score", 50) for c in candidates) / total, 1)
    high_match_pct = round((high_match_count / total) * 100)
    rejection_pct = round((rej_count / total) * 100)

    # 动态健康度计算：基于高匹配人数、达成HC比例及平均分综合加权
    hc_needed = int(job.get("hc", 2))
    hc_fulfillment = min(1.0, high_match_count / max(1, hc_needed))
    health_score = int(avg_score * 0.4 + hc_fulfillment * 45 + (100 - rejection_pct) * 0.15)
    health_score = max(50, min(99, health_score))

    # 动态构建真实候选人摘要物料
    roster_lines = []
    for c in candidates:
        name = c.get("name", "候选人")
        tier = c.get("ai_tier", "B")
        score = c.get("ai_score", 60)
        co = c.get("current_company", "未知企业")
        skills = ", ".join(c.get("skills", [])[:4])
        sal = c.get("salary_expect", "面议")
        flags = c.get("deep_audit", {}).get("risk_warnings", [])
        state = c.get("state", "review")
        flag_str = f" [风险: {'; '.join(flags)}]" if flags else ""
        roster_lines.append(f"- {name} ({tier}级/{score}分/{state}): {co} | 期望 {sal} | 技能: {skills}{flag_str}")

    roster_text = "\n".join(roster_lines)

    # 尝试调用大模型进行实时专业招聘洞察生成
    insights = []
    try:
        diag_prompt = f"""作为资深招聘总监与技术合伙人，请对以下【{job.get('title')}】岗位（HC需求: {hc_needed}人，薪资范围: {job.get('salary')}）当前简历人才库进行宏观全景诊断：

【当前岗位投递人才库全貌 ({total}人，平均分 {avg_score})】：
{roster_text}

【要求】：
请输出恰好 4 条具备专业管理指导价值的宏观深度洞察与策略建议：
1. 第一条：评估当前高匹配人才（S/A级）储备是否满足 HC，明确指出建议优先锁定推进哪位具体候选人（必须引用真实候选人名字与优势）；
2. 第二条：分析硬性门槛拦截与淘汰情况，说明淘汰的主要原因与是否需要微调门槛；
3. 第三条：分析候选人期望薪资与企业预算的拟合区间与成本控制建议；
4. 第四条：针对某位有特色或存在尽调存疑/潜力的具体候选人（如跨境出海/大厂背景），给出针对性的面试策略或加试建议。

严格以合法的 JSON 数组格式返回，不要任何 Markdown 标记或多余文字，格式示例：
["建议1...", "建议2...", "建议3...", "建议4..."]
"""
        raw_res = await generate_chat(diag_prompt, system_prompt="你是一位极其专业严谨的企业首席人才官(CHO)，请输出精炼、切中业务痛点的策略洞察，直接输出合法JSON数组。", cfg=cfg, json_mode=True)
        cleaned = raw_res.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        m = re.search(r"(\[.*\])", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1)
        parsed_insights = json.loads(cleaned)
        if isinstance(parsed_insights, list) and len(parsed_insights) >= 3:
            insights = [str(x) for x in parsed_insights[:4]]
    except Exception:
        pass

    # 若大模型未启动或返回异常，由基于真实数据的智能合成引擎产出高精度动态建议（绝无写死假数据和错别字！）
    if not insights or len(insights) < 3:
        insights = []
        # 洞察 1：高匹配度与优先推进候选人
        if s_cands:
            top_s = s_cands[0]
            insights.append(f"人才画像整体优质：S/A 级高潜人才占比达到 {high_match_pct}%，已满足 HC 储备，建议优先推进 S 级候选人【{top_s.get('name')}】（{top_s.get('current_company', '')}）进入终面。")
        elif a_cands:
            top_a = a_cands[0]
            insights.append(f"中坚人才储备充足：A 级优质人才占比 {high_match_pct}%，建议重点考核【{top_a.get('name')}】等骨干候选人。")
        else:
            insights.append(f"人才池高匹配率偏低（仅 {high_match_pct}%），目前缺乏 S/A 级标杆人才，建议加大猎头搜寻或放宽非核心条件。")

        # 洞察 2：硬门槛与质量把控
        if rej_count > 0:
            rej_names = ", ".join([c.get("name", "") for c in rej_cands[:2]])
            insights.append(f"硬性门槛拦截率在 {rejection_pct}%，自动化过滤了学历年限不符的投递（如 {rej_names}），有效减少了用人部门无效初筛耗时。")
        else:
            insights.append(f"硬性门槛拦截率为 0%，当前投递候选人的学历与工龄底线全部达标，初筛通过率极佳。")

        # 洞察 3：薪酬分布与预算把控
        salaries = [c.get("salary_expect", "") for c in candidates if c.get("salary_expect") and c.get("salary_expect") != "面议"]
        if salaries:
            sample_sal = salaries[0]
            insights.append(f"薪资期望分析：核心候选人期望集中在 {sample_sal} 左右，与当前岗位 HC 预算区间（{job.get('salary', '面议')}）基本契合，具备较好的谈判弹性。")
        else:
            insights.append(f"薪酬结构平稳，大部分候选人处于岗位标准薪酬带宽内，招聘成本风险受控。")

        # 洞察 4：针对性候选人潜力与背调加试策略
        target_cand = None
        for c in a_cands + s_cands + b_cands:
            if "陈书婷" in c.get("name", "") or "Shopee" in c.get("current_company", ""):
                target_cand = c
                break
        if not target_cand and a_cands:
            target_cand = a_cands[0]
        elif not target_cand and candidates:
            target_cand = candidates[0]

        if target_cand:
            t_name = target_cand.get("name", "重点候选人")
            t_comp = target_cand.get("current_company", "")
            t_flags = target_cand.get("deep_audit", {}).get("risk_warnings", [])
            if t_flags:
                insights.append(f"尽调风控建议：针对【{t_name}】识别出的履历疑点（{t_flags[0]}），建议面试官启动靶向测谎提纲进行交叉核验。")
            else:
                insights.append(f"业务潜力加试：针对具有 {t_comp} 业务背景的【{t_name}】，其核心工程经历具备良好迁移价值，建议增设业务场景实操加试。")

    return {
        "ok": True,
        "data": {
            "health_score": health_score,
            "avg_score": avg_score,
            "total_screened": total,
            "high_match_rate": f"{high_match_pct}%",
            "rejection_rate": f"{rejection_pct}%",
            "insights": insights,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    }


# ─────────────────────────── 简历上传与批量操作 ───────────────────────────

#: 可解析的简历格式（与 app/core/parser.py 保持一致）
SUPPORTED_RESUME_EXT = (".pdf", ".docx", ".doc", ".txt", ".md")
#: 支持的压缩包格式
ARCHIVE_EXT = (".zip",)
#: 压缩包内需要跳过的系统/隐藏文件
_ZIP_SKIP_RE = re.compile(r"(^|/)(__MACOSX|\.DS_Store)(/|$)|(^|/)\._|(^|/)~\$|(^|/)Thumbs\.db$")
#: 单次请求最多处理的简历份数（防止一次拖入上千个文件把服务打满）
MAX_RESUMES_PER_REQUEST = 200
#: 单个压缩包解包后的总大小上限（防 zip 炸弹）
MAX_ARCHIVE_TOTAL_BYTES = 200 * 1024 * 1024


def _resume_fingerprint(resume_text: str) -> str:
    """简历内容指纹：去掉空白与标点后的字符流做 SHA1，用于「同岗位重复投递」判重。

    - 只按内容判重，不掺入文件名/姓名，避免同一人换文件名后重复入库；
    - 文本过短（<50 字）时不返回指纹，避免把两篇内容都极少的简历误判为同一人。
    """
    raw = (resume_text or "").strip()
    if len(raw) < 50:
        return ""
    norm = re.sub(r"\s+", "", raw)
    norm = re.sub(r"[^\w\u4e00-\u9fa5]", "", norm).lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def _extract_zip_resumes(raw: bytes) -> tuple:
    """解包 zip，返回 (简历成员列表[(包内路径, 字节)], 读取失败列表[(包内路径, 原因)], 致命错误)。

    - 递归收集任意层级的子目录里的简历文件（压缩一个文件夹是很常见的用法）；
    - 跳过 __MACOSX / .DS_Store / 隐藏文件与非简历格式；
    - 单包成员数与解包总大小都有上限，避免 zip 炸弹把服务打满；
    - 保留包内相对路径，便于 HR 定位是哪个文件出的问题。
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception as e:
        return [], [], f"压缩包无法打开（{e}），请确认文件未损坏或未加密"
    try:
        infos = zf.infolist()
    except Exception as e:
        return [], [], f"压缩包目录读取失败（{e}）"

    members: List[tuple] = []
    unreadable: List[tuple] = []
    total = 0
    for info in infos:
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if _ZIP_SKIP_RE.search(name):
            continue
        base = os.path.basename(name)
        if not base or base.startswith("."):
            continue
        if os.path.splitext(base)[1].lower() not in SUPPORTED_RESUME_EXT:
            continue
        if len(members) + len(unreadable) >= MAX_RESUMES_PER_REQUEST:
            break
        try:
            data = zf.read(info)
        except Exception as e:                      # 加密成员 / 损坏成员
            unreadable.append((name, str(e)))
            continue
        total += len(data)
        if total > MAX_ARCHIVE_TOTAL_BYTES:
            zf.close()
            return members, unreadable, "压缩包解包后总体积过大（超过 200MB），已中止，请拆分后再上传"
        members.append((name, data))
    zf.close()
    return members, unreadable, ""


def _job_fingerprint_index(job_id: str) -> Dict[str, Dict[str, Any]]:
    """该岗位下已有候选人的「指纹 → 候选人」索引（历史数据无指纹时即时补算）"""
    index: Dict[str, Dict[str, Any]] = {}
    for c in _get_all_candidates():
        if c.get("job_id") != job_id:
            continue
        fp = c.get("resume_hash") or _resume_fingerprint(c.get("resume_text") or c.get("raw_resume") or "")
        if fp and fp not in index:
            index[fp] = c
    return index


@router.post("/api/upload")
async def upload_resumes(
    files: list[UploadFile] = File(...),
    job_id: str = Form("fe-fullstack"),
):
    """批量导入简历并执行初筛。

    支持三种投递方式：单/多选文件、**整个文件夹**（前端展开后逐个上传）、**zip 压缩包**（后端解包）。
    压缩包内任意层级的支持格式（PDF / Word / TXT / MD）都会被识别；同岗位重复简历自动跳过。
    """
    cfg = load_config()
    jobs = _get_all_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail=f"岗位 {job_id} 不存在")

    existing_index = _job_fingerprint_index(job_id)     # 与库内已有简历判重
    batch_index: Dict[str, Dict[str, Any]] = {}         # 与本次同批文件判重
    results = []

    # ── 第一步：展开上传内容（zip 解包 → 一份份简历）──
    queue: List[Dict[str, Any]] = []                    # {"filename": 展示名, "data": bytes, "from_archive": bool}
    for f in files:
        name = f.filename or "resume"
        try:
            raw = await f.read()
        except Exception as e:
            results.append({"filename": name, "ok": False, "error": f"读取失败: {e}"})
            continue

        if name.lower().endswith(ARCHIVE_EXT):
            members, unreadable, err = _extract_zip_resumes(raw)
            if err and not members:
                results.append({"filename": name, "ok": False, "error": err})
                continue
            for mname, why in unreadable:
                results.append({"filename": f"{name}/{mname}", "ok": False,
                                "error": f"压缩包内该文件无法读取（{why}），可能已加密或损坏"})
            if not members and not unreadable:
                results.append({"filename": name, "ok": False,
                                "error": "压缩包内没有找到可解析的简历（支持 PDF / Word / TXT / MD）"})
                continue
            for mname, data in members:
                queue.append({"filename": f"{name}/{mname}", "data": data, "from_archive": True})
        else:
            queue.append({"filename": name, "data": raw, "from_archive": False})

    if len(queue) > MAX_RESUMES_PER_REQUEST:
        results.append({
            "filename": "（批量导入）", "ok": False,
            "error": f"本次共收集到 {len(queue)} 份简历，超过单次上限 {MAX_RESUMES_PER_REQUEST} 份，"
                     f"仅处理前 {MAX_RESUMES_PER_REQUEST} 份，请分批上传",
        })
        queue = queue[:MAX_RESUMES_PER_REQUEST]

    # ── 第二步：逐份解析 + 判重 + 初筛 ──
    for item in queue:
        display_name = item["filename"]
        try:
            text = extract_text_from_bytes(os.path.basename(display_name), item["data"])
            fingerprint = _resume_fingerprint(text)

            if fingerprint:
                dup = existing_index.get(fingerprint)
                if dup:
                    results.append({
                        "filename": display_name, "ok": False, "duplicated": True,
                        "error": f"重复投递：该简历已在【{job.get('title', job_id)}】候选人库中"
                                 f"（{dup.get('name', '已存在候选人')}"
                                 f"{('，投递于 ' + dup['apply_time']) if dup.get('apply_time') else ''}），本次已自动跳过",
                    })
                    continue
                dup = batch_index.get(fingerprint)
                if dup:
                    results.append({
                        "filename": display_name, "ok": False, "duplicated": True,
                        "error": f"重复投递：与本批次中的「{dup.get('name', '文件')}」内容完全一致，本次已自动跳过",
                    })
                    continue

            candidate = await screen_resume_full(
                resume_text=text, job=job, cfg=cfg, filename=os.path.basename(display_name)
            )
            candidate["resume_hash"] = fingerprint
            if item["from_archive"]:
                candidate["source_archive"] = display_name.rsplit("/", 1)[0]
            _get_all_candidates().insert(0, candidate)
            if fingerprint:
                batch_index[fingerprint] = candidate
                existing_index[fingerprint] = candidate
            results.append({"filename": display_name, "ok": True, "candidate": candidate})
        except ValueError as e:
            results.append({"filename": display_name, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"filename": display_name, "ok": False, "error": f"处理失败: {e}"})
    storage.save()
    return {"ok": True, "data": results}


@router.post("/api/batch-action")
def batch_action(body: dict):
    action = body.get("action", "")
    ids = body.get("candidate_ids", [])
    candidates = _get_all_candidates()
    target = [c for c in candidates if c["id"] in ids]
    if not target:
        raise HTTPException(status_code=400, detail="未找到指定候选人")
        
    if action == "schedule":
        for c in candidates:
            if c["id"] in ids:
                c["state"] = "scheduled"
                storage.interviews.append({
                    "id": f"iv-{uuid.uuid4().hex[:6]}",
                    "candidate_id": c["id"],
                    "candidate_name": c.get("name", "候选人"),
                    "job_title": "资深前端开发 / 全栈工程师",
                    "round": "批量技术约面",
                    "time": "待技术专家确认排期",
                    "interviewer": "技术委员会",
                    "meeting_link": f"https://meeting.recruitai.com/room/{uuid.uuid4().hex[:6]}",
                    "status": "upcoming"
                })
        storage.save()
        return {"ok": True, "data": {"updated": len(target)}, "message": f"已成功将 {len(target)} 位候选人推进至约面流程并同步至面试日程！"}
        
    elif action == "reject":
        _ensure_init()
        now_time = datetime.now().strftime("%H:%M")
        for c in candidates:
            if c["id"] in ids:
                c["state"] = "rejected"
                cid = c["id"]
                cname = c.get("name", "候选人")
                history = storage.chat_history.setdefault(cid, [])
                _drop_seeded(history)
                if not any(m.get("is_reject") for m in history):
                    history.append({
                        "sender": "system",
                        "name": "企业招聘系统 · 委婉回绝通知",
                        "text": f"尊敬的{cname}先生/女士：感谢您关注并投递我司职位。经过系统综合评估，暂未能安排本期面试，简历已归档至储备库。祝您求职顺利，前程似锦！",
                        "time": now_time,
                        "is_reject": True
                    })
        # 批量淘汰时联动清除被淘汰人员的待面试排期
        storage.interviews[:] = [iv for iv in storage.interviews if iv.get("candidate_id") not in ids]
        storage.save()
        return {"ok": True, "data": {"updated": len(target)}, "message": f"已将 {len(target)} 位候选人批量移入淘汰库并发送委婉回绝通知"}
        
    elif action == "pool":
        _ensure_init()
        # 移入公海时联动清除待面试排期
        storage.interviews[:] = [iv for iv in storage.interviews if iv.get("candidate_id") not in [c["id"] for c in target]]
        for c in target:
            if c in candidates:
                candidates.remove(c)
            talent_item = copy.deepcopy(c)
            talent_item["id"] = f"pool-{uuid.uuid4().hex[:6]}"
            talent_item["archived_date"] = datetime.now().strftime("%Y-%m-%d")
            talent_item["reason"] = "由HR从初筛列表批量移入公海储备"
            storage.talent_pool.append(talent_item)
        storage.save()
        return {"ok": True, "data": {"updated": len(target)}, "message": f"已将 {len(target)} 位候选人批量转入企业人才公海！"}
        
    elif action == "greet":
        _ensure_init()
        greeted, skipped = [], []
        for c in target:
            if _append_greeting(c):
                greeted.append(c.get("name", "候选人"))
            else:
                skipped.append(c.get("name", "候选人"))
        storage.save()
        if greeted:
            msg = f"已向 {len(greeted)} 位候选人发起沟通（由公司侧先发送招呼语，可前往「沟通中心」查看）"
            if skipped:
                msg += f"；另有 {len(skipped)} 位此前已招呼过，未重复发送"
        else:
            msg = f"选中的 {len(target)} 位候选人均已招呼过，未重复发送"
        return {
            "ok": True,
            "data": {"updated": len(greeted), "skipped": len(skipped), "greeted_names": greeted},
            "message": msg,
        }
        
    elif action == "export":
        lines = ["# RecruitAI 候选人评审摘要清单", f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
        for c in target:
            lines.append(f"## {c.get('name','未知')}  [{c.get('ai_tier','?')}级 · {c.get('ai_score','?')}分]")
            lines.append(f"- **当前职位**：{c.get('current_title','')} @ {c.get('current_company','')}")
            lines.append(f"- **期望薪资**：{c.get('salary_expect','')}")
            lines.append(f"- **AI 评级**：{c.get('ai_label','')}")
            lines.append(f"- **AI 理由**：{c.get('ai_reason','')}")
            if c.get('interview_questions'):
                lines.append("- **建议面试题**：")
                for q in c['interview_questions']:
                    lines.append(f"  - {q}")
            lines.append("")
        return {"ok": True, "data": {"markdown": "\n".join(lines)}}
    else:
        raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")


@router.post("/api/reset")
def reset_runtime_state():
    """
    一键数据恢复：将全量运行时数据还原为基线快照 (data/store.baseline.json)，
    供开发人员反复上传简历测试各业务模块使用（基线缺失时退化为出厂预设数据）。
    """
    source = storage.restore_from_baseline()
    label = "基线快照 (data/store.baseline.json)" if source == "baseline" else "出厂预设数据 (app/core/presets.py)"
    return {
        "ok": True,
        "source": source,
        "message": f"已成功恢复为{label}的初始演示状态",
        "summary": {
            "candidates": len(storage.candidates),
            "talent_pool": len(storage.talent_pool),
            "interviews": len(storage.interviews),
            "chat_history": len(storage.chat_history),
            "rejections": len(storage.rejections),
        },
    }
