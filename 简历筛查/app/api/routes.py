import copy
import uuid
from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import CLOUD_PRESETS, load_config, save_config
from app.core.llm_client import get_model_status, test_cloud_connection
from app.core.parser import extract_text_from_bytes
from app.core.presets import PRESET_CANDIDATES, PRESET_JOBS
from app.core.screening import screen_resume_full

router = APIRouter()

_runtime_candidates: list = []
_runtime_jobs: list = []
_runtime_interviews: list = []
_runtime_talent_pool: list = []
_runtime_chat_history: dict = {}
_runtime_rejections: list = []
_initialized = False


def _ensure_init():
    global _initialized
    if not _initialized:
        _runtime_candidates.extend(copy.deepcopy(PRESET_CANDIDATES))
        _runtime_jobs.extend(copy.deepcopy(PRESET_JOBS))
        
        # 预设面试日程：严格与初始 scheduled 状态的候选人（林远志）对齐 (counts.scheduled == 1)
        _runtime_interviews.extend([
            {
                "id": "iv-001",
                "candidate_id": "preset-001",
                "candidate_name": "林远志",
                "job_title": "资深前端开发 / 全栈工程师",
                "round": "业务初试 (视频)",
                "time": "今日 14:30 - 15:30",
                "interviewer": "架构师 · 张工",
                "meeting_link": "https://meeting.recruitai.com/room/888-999",
                "status": "upcoming"
            }
        ])
        
        # 预设公海人才
        _runtime_talent_pool.extend([
            {
                "id": "pool-001",
                "name": "孙立强",
                "age": 30,
                "experience_years": 7,
                "education": "bachelor",
                "school": "华中科技大学 (985)",
                "skills": ["Vue3", "TypeScript", "WebGL", "Three.js"],
                "current_company": "字节跳动",
                "current_title": "图形可视化架构师",
                "ai_score": 89,
                "ai_tier": "A",
                "archived_date": "2025-08-15",
                "reason": "上期HC满员转入公海战略储备"
            },
            {
                "id": "pool-002",
                "name": "郭少华",
                "age": 33,
                "experience_years": 10,
                "education": "master",
                "school": "同济大学 (985)",
                "skills": ["Node.js", "Go", "K8s", "微服务架构"],
                "current_company": "拼多多",
                "current_title": "服务端高可用架构专家",
                "ai_score": 93,
                "ai_tier": "S",
                "archived_date": "2025-07-20",
                "reason": "薪酬超预算暂存公海"
            }
        ])

        _initialized = True


def _get_all_candidates():
    _ensure_init()
    return _runtime_candidates


def _get_all_jobs():
    _ensure_init()
    return _runtime_jobs


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
    jobs.insert(0, new_job)
    return {"ok": True, "data": new_job}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    jobs = _get_all_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return {"ok": True, "data": job}


@router.put("/api/jobs/{job_id}")
def update_job(job_id: str, body: dict):
    jobs = _get_all_jobs()
    for i, j in enumerate(jobs):
        if j["id"] == job_id:
            jobs[i].update({k: v for k, v in body.items() if k != "id"})
            return {"ok": True, "data": jobs[i]}
    raise HTTPException(status_code=404, detail="岗位不存在")


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
                existing = next((iv for iv in _runtime_interviews if iv.get("candidate_id") == candidate_id), None)
                if not existing:
                    if candidate_id == "preset-002":
                        _runtime_interviews.append({
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
                        _runtime_interviews.append({
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
                _runtime_interviews[:] = [iv for iv in _runtime_interviews if iv.get("candidate_id") != candidate_id]

            # 如果是回绝状态，联动注入回绝通知到聊天记录中
            if new_state == "rejected":
                cid = c["id"]
                cname = c.get("name", "候选人")
                history = _runtime_chat_history.setdefault(cid, [
                    {
                        "sender": "candidate",
                        "name": cname,
                        "text": f"您好！我是{cname}，我对贵司的这个岗位非常感兴趣。我的核心履历已经通过系统初筛，期待与您深入交流！",
                        "time": "今天 09:30"
                    }
                ])
                if not any(m.get("is_reject") for m in history):
                    history.append({
                        "sender": "system",
                        "name": "企业招聘系统 · 委婉回绝通知",
                        "text": f"尊敬的{cname}先生/女士：感谢您关注并投递我司职位。经过系统综合评估与招聘委员会审阅，您的经历非常值得赞赏，但鉴于本次HC名额有限及当下技术栈契合度考量，暂未能安排本期面试。您的简历已纳入我司战略人才储备库。祝您求职顺利！",
                        "time": datetime.now().strftime("%H:%M"),
                        "is_reject": True
                    })
            return {"ok": True, "data": c}
    raise HTTPException(status_code=404, detail="候选人不存在")


@router.post("/api/candidates/{candidate_id}/generate-questions")
def regenerate_questions(candidate_id: str):
    """根据候选人背景重新生成 3 道个性化针对性面试问题"""
    candidates = _get_all_candidates()
    c = next((x for x in candidates if x["id"] == candidate_id), None)
    if not c:
        raise HTTPException(status_code=404, detail="候选人不存在")
    
    name = c.get("name", "候选人")
    skills = " / ".join(c.get("skills", ["核心技术栈"]))
    new_questions = [
        f"结合你在【{c.get('current_company','过往企业')}】的经历，请详述如何保证【{skills}】在千万级并发下的可靠性与可用性？",
        f"你在过往技术沉淀中，做过的最具技术挑战性的性能优化指标（如首屏渲染、网络吞吐）是如何量化衡量的？",
        f"如果业务线需要你主导跨端技术方案选型与研发团队技术培训，你将如何制定前30天的技术落地里程碑？"
    ]
    c["interview_questions"] = new_questions
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
    _runtime_rejections.append(notice)
    
    # 核心闭环：同步注入到该候选人的微聊沟通记录中
    _ensure_init()
    history = _runtime_chat_history.setdefault(candidate_id, [
        {
            "sender": "candidate",
            "name": c.get("name", "候选人"),
            "text": f"您好！我是{c.get('name')}，我对贵司的这个岗位非常感兴趣。我的核心履历已经通过系统初筛，期待与您深入交流！",
            "time": "今天 09:30"
        }
    ])
    if not any(m.get("is_reject") for m in history):
        history.append({
            "sender": "system",
            "name": "企业招聘系统 · 委婉回绝通知",
            "text": notice_text,
            "time": now_str,
            "is_reject": True
        })
        
    return {"ok": True, "data": notice, "message": f"已向候选人【{c.get('name')}】发送标准化委婉回绝通知及感谢信"}


# ─────────────────────────── 真实候选人对话沟通接口 ───────────────────────────

@router.get("/api/chats")
def list_chats(job_id: str = ""):
    """获取沟通中心的候选人沟通列表及最新消息摘要"""
    _ensure_init()
    candidates = _get_all_candidates()
    if job_id:
        candidates = [c for c in candidates if c.get("job_id") == job_id]
    result = []
    for c in candidates:
        cid = c["id"]
        cname = c.get("name", "候选人")
        hist = _runtime_chat_history.get(cid)
        if hist is None:
            hist = [
                {
                    "sender": "candidate",
                    "name": cname,
                    "text": f"您好！我是{cname}，我对贵司的这个岗位非常感兴趣。我的核心履历已经通过系统初筛，期待与您深入交流！",
                    "time": "今天 09:30"
                }
            ]
            if c.get("state") == "rejected":
                hist.append({
                    "sender": "system",
                    "name": "企业招聘系统 · 委婉回绝通知",
                    "text": f"尊敬的{cname}先生/女士：感谢您关注并投递我司职位。经过系统综合评估与审阅，暂未能安排本期面试。您的简历已纳入战略人才储备库。祝求职顺利！",
                    "time": "今天 10:15",
                    "is_reject": True
                })
            _runtime_chat_history[cid] = hist
        
        last_msg = hist[-1] if hist else {}
        result.append({
            "candidate_id": cid,
            "candidate": c,
            "last_message": last_msg.get("text", ""),
            "last_sender": last_msg.get("sender", ""),
            "last_time": last_msg.get("time", ""),
            "is_rejected": any(m.get("is_reject") for m in hist) or c.get("state") == "rejected"
        })
    return {"ok": True, "data": result}


@router.get("/api/candidates/{candidate_id}/chat")
def get_chat_history(candidate_id: str):
    _ensure_init()
    c = next((x for x in _get_all_candidates() if x["id"] == candidate_id), None)
    cname = c["name"] if c else "候选人"
    history = _runtime_chat_history.get(candidate_id)
    if history is None:
        history = [
            {
                "sender": "candidate",
                "name": cname,
                "text": f"您好！我是{cname}，我对贵司的这个岗位非常感兴趣。我的核心履历已经通过系统初筛，期待与您深入交流！",
                "time": "今天 09:30"
            }
        ]
        # 若候选人已经是 rejected 状态，自动带上回绝信
        if c and c.get("state") == "rejected":
            history.append({
                "sender": "system",
                "name": "企业招聘系统 · 委婉回绝通知",
                "text": f"尊敬的{cname}先生/女士：感谢您关注并投递我司职位。经过系统综合评估与招聘委员会审阅，您的经历非常值得赞赏，但鉴于本次HC名额有限及当下技术栈契合度考量，暂未能安排本期面试。您的简历已纳入我司企业人才储备库。祝您求职顺利！",
                "time": "今天 10:15",
                "is_reject": True
            })
        _runtime_chat_history[candidate_id] = history
    else:
        # 如果已经存在 history 但候选人是 rejected 状态且还没有回绝消息，自动补齐
        if c and c.get("state") == "rejected" and not any(m.get("is_reject") for m in history):
            history.append({
                "sender": "system",
                "name": "企业招聘系统 · 委婉回绝通知",
                "text": f"尊敬的{cname}先生/女士：感谢您关注并投递我司职位。经过系统综合评估与招聘委员会审阅，您的经历非常值得赞赏，但鉴于本次HC名额有限及当下技术栈契合度考量，暂未能安排本期面试。您的简历已纳入我司企业人才储备库。祝您求职顺利！",
                "time": datetime.now().strftime("%H:%M"),
                "is_reject": True
            })
    return {"ok": True, "data": history}


@router.post("/api/candidates/{candidate_id}/chat")
def send_chat_message(candidate_id: str, body: dict):
    _ensure_init()
    msg_text = body.get("message", "").strip()
    if not msg_text:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
        
    history = _runtime_chat_history.setdefault(candidate_id, [])
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
    
    reply = f"好的，感谢HR老师的认可！我工作日随时可配合线上面试。若有技术笔试或作品集要求，我也能立即提交！"
    if "到岗" in msg_text:
        reply = f"关于到岗时间：我目前状态为{c.get('available_time','随时到岗')}，如果聊得顺利，一周内即可正式入职！"
    elif "薪资" in msg_text or "期望" in msg_text:
        reply = f"关于薪资期望：我的预期范围是 {c.get('salary_expect','25-35K')}，可以根据公司具体的职级和福利结构综合沟通！"
    elif "并发" in msg_text or "架构" in msg_text or "微前端" in msg_text:
        reply = f"关于技术经验：我在过往经历中主导过微前端子应用架构与千万级并发优化，线上面试中我很乐意分享具体的落地方案与指标！"
    elif "面试" in msg_text or "时间" in msg_text:
        reply = f"太好了！我这周三下午或周五上午时间都很充裕，可以直接安排腾讯会议/飞书视频面试，静候您的日历邀约！"

    history.append({
        "sender": "candidate",
        "name": cname,
        "text": reply,
        "time": now_str
    })
    
    return {"ok": True, "data": {"reply": reply, "history": history}}


# ─────────────────────────── 面试日程管理接口 ───────────────────────────

@router.get("/api/interviews")
def list_interviews(job_id: str = "fe-fullstack"):
    _ensure_init()
    candidates_map = {c["id"]: c for c in _get_all_candidates()}
    # 严格对齐：仅返回关联候选人当前状态仍为 scheduled 的有效排期
    active_ivs = []
    for iv in _runtime_interviews:
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
    _runtime_interviews.append(item)
    if c:
        c["state"] = "scheduled"
    return {"ok": True, "data": item}


@router.patch("/api/interviews/{interview_id}")
def update_interview(interview_id: str, body: dict):
    _ensure_init()
    iv = next((x for x in _runtime_interviews if x["id"] == interview_id), None)
    if not iv:
        raise HTTPException(status_code=404, detail="面试日程不存在")
    iv.update(body)
    return {"ok": True, "data": iv}


# ─────────────────────────── 人才公海接口 ───────────────────────────

@router.get("/api/talent-pool")
def list_talent_pool():
    _ensure_init()
    return {"ok": True, "data": _runtime_talent_pool}


@router.post("/api/talent-pool/restore")
def restore_talent(body: dict):
    _ensure_init()
    pool_id = body.get("pool_id") or body.get("candidate_id") or body.get("id")
    target = next((x for x in _runtime_talent_pool if x["id"] == pool_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="公海候选人不存在")
        
    _runtime_talent_pool.remove(target)
    target_job = body.get("target_job_id", "fe-fullstack")
    new_candidate = {
        "id": f"restored-{uuid.uuid4().hex[:6]}",
        "name": target.get("name"),
        "age": target.get("age", 29),
        "job_id": target_job,
        "status": "available",
        "available_time": "随时到岗",
        "apply_time": datetime.now().strftime("%H:%M"),
        "experience_years": target.get("experience_years", 6),
        "education": target.get("education", "bachelor"),
        "school": target.get("school", "知名高校"),
        "school_tier": "985",
        "major": "计算机",
        "current_company": target.get("current_company", "知名大厂"),
        "current_title": target.get("current_title", "资深架构师"),
        "salary_expect": "28-35K",
        "skills": target.get("skills", ["Vue3", "TypeScript", "微服务"]),
        "verified": True,
        "ai_score": target.get("ai_score", 88),
        "ai_tier": target.get("ai_tier", "A"),
        "ai_label": "公海重新激活",
        "ai_reason": "从企业人才公海池高匹配库重新激活入池，其技术栈与项目体量高度贴合本岗位需求。",
        "radar": {"技术深度": 88, "项目规模": 85, "技术栈匹配": 90, "学历背景": 92, "发展潜力": 88},
        "tags": ["✓ 公海核心储备", "✓ 资质核验完成", "✓ 高契合度画像"],
        "interview_questions": [
            "请介绍你在大厂经历中主导过的最核心技术架构方案？",
            "重新看新的工作机会，你对本业务线最关注的技术切入点是什么？"
        ],
        "state": "recommended"
    }
    _runtime_candidates.insert(0, new_candidate)
    return {"ok": True, "data": new_candidate}


# ─────────────────────────── AI 智能全景诊断报告 ───────────────────────────

@router.get("/api/diagnostics")
def run_diagnostics(job_id: str = "fe-fullstack"):
    candidates = [c for c in _get_all_candidates() if c.get("job_id") == job_id]
    total = len(candidates)
    if total == 0:
        return {"ok": True, "data": {"health_score": 75, "summary": "暂无投递样本"}}
        
    s_count = sum(1 for c in candidates if c.get("ai_tier") == "S")
    a_count = sum(1 for c in candidates if c.get("ai_tier") == "A")
    rej_count = sum(1 for c in candidates if c.get("state") == "rejected")
    avg_score = round(sum(c.get("ai_score", 50) for c in candidates) / total, 1)
    
    return {
        "ok": True,
        "data": {
            "health_score": 92,
            "avg_score": avg_score,
            "total_screened": total,
            "high_match_rate": f"{round((s_count + a_count) / total * 100)}%",
            "rejection_rate": f"{round(rej_count / total * 100)}%",
            "insights": [
                "人才池画像极佳：S/A 级高匹配人才占比超过 50%，建议尽快锁定 S 级候选人（林远志）一面；",
                "硬性门槛拦截率稳定在 25%，有效过滤了年限学历不符的无效投递；",
                "候选人平均期望薪资集中在 28-35K，完全处于企业 HC 预算安全区间；",
                "建议针对 Shopee 背景的陈书廷发起加试，其跨境电商海外协同经历具备高潜力。"
            ]
        }
    }


# ─────────────────────────── 简历上传与批量操作 ───────────────────────────

@router.post("/api/upload")
async def upload_resumes(
    files: list[UploadFile] = File(...),
    job_id: str = Form("fe-fullstack"),
):
    cfg = load_config()
    jobs = _get_all_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail=f"岗位 {job_id} 不存在")
    results = []
    for f in files:
        try:
            file_bytes = await f.read()
            text = extract_text_from_bytes(f.filename or "resume.txt", file_bytes)
            candidate = await screen_resume_full(
                resume_text=text, job=job, cfg=cfg, filename=f.filename or ""
            )
            _get_all_candidates().insert(0, candidate)
            results.append({"filename": f.filename, "ok": True, "candidate": candidate})
        except ValueError as e:
            results.append({"filename": f.filename, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"filename": f.filename, "ok": False, "error": f"处理失败: {e}"})
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
                _runtime_interviews.append({
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
        return {"ok": True, "data": {"updated": len(target)}, "message": f"已成功将 {len(target)} 位候选人推进至约面流程并同步至面试日程！"}
        
    elif action == "reject":
        _ensure_init()
        now_time = datetime.now().strftime("%H:%M")
        for c in candidates:
            if c["id"] in ids:
                c["state"] = "rejected"
                cid = c["id"]
                cname = c.get("name", "候选人")
                history = _runtime_chat_history.setdefault(cid, [
                    {
                        "sender": "candidate",
                        "name": cname,
                        "text": f"您好！我是{cname}，我对贵司的这个岗位非常感兴趣。我的核心履历已经通过系统初筛，期待与您深入交流！",
                        "time": "今天 09:30"
                    }
                ])
                if not any(m.get("is_reject") for m in history):
                    history.append({
                        "sender": "system",
                        "name": "企业招聘系统 · 委婉回绝通知",
                        "text": f"尊敬的{cname}先生/女士：感谢您关注并投递我司职位。经过系统综合评估，暂未能安排本期面试，简历已归档至储备库。祝您求职顺利，前程似锦！",
                        "time": now_time,
                        "is_reject": True
                    })
        # 批量淘汰时联动清除被淘汰人员的待面试排期
        _runtime_interviews[:] = [iv for iv in _runtime_interviews if iv.get("candidate_id") not in ids]
        return {"ok": True, "data": {"updated": len(target)}, "message": f"已将 {len(target)} 位候选人批量移入淘汰库并发送委婉回绝通知"}
        
    elif action == "pool":
        _ensure_init()
        # 移入公海时联动清除待面试排期
        _runtime_interviews[:] = [iv for iv in _runtime_interviews if iv.get("candidate_id") not in [c["id"] for c in target]]
        for c in target:
            if c in candidates:
                candidates.remove(c)
            _runtime_talent_pool.append({
                "id": f"pool-{uuid.uuid4().hex[:6]}",
                "name": c.get("name"),
                "age": c.get("age", 28),
                "experience_years": c.get("experience_years", 5),
                "education": c.get("education", "bachelor"),
                "school": c.get("school", "大学"),
                "skills": c.get("skills", []),
                "current_company": c.get("current_company", ""),
                "current_title": c.get("current_title", ""),
                "ai_score": c.get("ai_score", 80),
                "ai_tier": c.get("ai_tier", "A"),
                "archived_date": datetime.now().strftime("%Y-%m-%d"),
                "reason": "由HR从初筛列表批量移入公海储备"
            })
        return {"ok": True, "data": {"updated": len(target)}, "message": f"已将 {len(target)} 位候选人批量转入企业人才公海！"}
        
    elif action == "greet":
        return {"ok": True, "data": {"updated": len(target)}, "message": f"已向选中的 {len(target)} 位候选人批量发送初筛问候！"}
        
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
    global _initialized
    _runtime_candidates.clear()
    _runtime_jobs.clear()
    _runtime_interviews.clear()
    _runtime_talent_pool.clear()
    _runtime_chat_history.clear()
    _runtime_rejections.clear()
    _initialized = False
    _ensure_init()
    return {"ok": True, "message": "已成功重置为初始预设演示状态"}
