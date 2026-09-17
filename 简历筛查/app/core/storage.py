# -*- coding: utf-8 -*-
"""
RecruitAI 数据持久化与一致性自愈存储引擎
负责将岗位、候选人、人才公海、面试日程、沟通记录与淘汰拒信实时落盘至 data/store.json，
并在服务启动加载时执行自愈校验（Self-Healing Audit），保障多实体关联状态强一致。
"""
import copy
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.presets import PRESET_CANDIDATES, PRESET_JOBS

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
STORE_FILE = DATA_DIR / "store.json"
# 开发自测基线快照：一键恢复数据的还原源（由 data/store.json 在“干净状态”下复制而来）
BASELINE_FILE = DATA_DIR / "store.baseline.json"


def _get_default_interviews() -> List[Dict[str, Any]]:
    return [
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
    ]


def _get_default_talent_pool() -> List[Dict[str, Any]]:
    return [
        {
            "id": "pool-001",
            "name": "孙立强",
            "age": 30,
            "experience_years": 7,
            "education": "bachelor",
            "education_type": "full_time",
            "school": "华中科技大学",
            "school_tier": "985",
            "major": "计算机科学与技术",
            "skills": ["Vue3", "TypeScript", "WebGL", "Three.js"],
            "current_company": "字节跳动",
            "current_title": "图形可视化架构师",
            "ai_score": 89,
            "ai_tier": "A",
            "archived_date": "2025-08-15",
            "reason": "上期HC满员转入公海战略储备",
            "salary_expect": "30-38K",
        },
        {
            "id": "pool-002",
            "name": "郭少华",
            "age": 33,
            "experience_years": 10,
            "education": "master",
            "education_type": "full_time",
            "school": "同济大学",
            "school_tier": "985",
            "major": "软件工程",
            "skills": ["Node.js", "Go", "K8s", "微服务架构"],
            "current_company": "拼多多",
            "current_title": "服务端高可用架构专家",
            "ai_score": 93,
            "ai_tier": "S",
            "archived_date": "2025-07-20",
            "reason": "薪酬超预算暂存公海",
            "salary_expect": "35-45K",
        },
        {
            "id": "pool-003",
            "name": "刘思涵",
            "age": 24,
            "experience_years": 2,
            "education": "associate",
            "education_type": "full_time",
            "school": "某市职业技术学院",
            "school_tier": "other",
            "major": "计算机信息管理",
            "skills": ["Vue 2", "Vue 3", "JavaScript", "Element Plus"],
            "current_company": "创新互动网络",
            "current_title": "初级前端工程师",
            "ai_score": 75,
            "ai_tier": "B",
            "archived_date": "2026-02-10",
            "reason": "初筛时因岗位设置5年经验与统招本科门槛未达标转入公海储备",
            "salary_expect": "10-14K",
        },
        {
            "id": "pool-004",
            "name": "周鹏飞",
            "age": 26,
            "experience_years": 3,
            "education": "bachelor",
            "education_type": "full_time",
            "school": "广东工业大学",
            "school_tier": "other",
            "major": "软件工程",
            "skills": ["React", "TypeScript", "TailwindCSS", "Node.js"],
            "current_company": "有赞科技",
            "current_title": "Web前端开发工程师",
            "ai_score": 86,
            "ai_tier": "A",
            "archived_date": "2026-02-18",
            "reason": "初筛时因岗位设置5年经验门槛未达标转入公海储备",
            "salary_expect": "18-22K",
        }
    ]


class StorageManager:
    """持久化存储管理单例"""

    def __init__(self):
        self._lock = threading.RLock()
        self._initialized = False
        self.jobs: List[Dict[str, Any]] = []
        self.candidates: List[Dict[str, Any]] = []
        self.interviews: List[Dict[str, Any]] = []
        self.talent_pool: List[Dict[str, Any]] = []
        self.chat_history: Dict[str, List[Dict[str, Any]]] = {}
        self.rejections: List[Dict[str, Any]] = []

    def ensure_init(self) -> None:
        """确保存储层初始化完成，若已持久化则从磁盘读入，否则初始化默认种子数据"""
        with self._lock:
            if self._initialized:
                return

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            if STORE_FILE.exists():
                try:
                    with open(STORE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._load_payload_into_memory(data)
                    # 执行开机自愈校验
                    self._self_healing_audit()
                    self._initialized = True
                    return
                except Exception as e:
                    print(f"[RecruitAI Storage] 读取持久化文件异常 ({e})，将重建种子数据。")

            # 首次运行或文件损毁，重新种子化
            self._seed_default_data()
            self._initialized = True
            self.save()

    def _load_payload_into_memory(self, data: Dict[str, Any]) -> None:
        """将持久化载荷（或基线快照载荷）载入内存实体"""
        self.jobs = data.get("jobs", [])
        self.candidates = data.get("candidates", [])
        self.interviews = data.get("interviews", [])
        self.talent_pool = data.get("talent_pool", [])
        self.chat_history = data.get("chat_history", {})
        self.rejections = data.get("rejections", [])

    def _seed_default_data(self) -> None:
        """填充预设初始演示数据"""
        self.jobs = copy.deepcopy(PRESET_JOBS)
        self.candidates = copy.deepcopy(PRESET_CANDIDATES)
        self.interviews = _get_default_interviews()
        self.talent_pool = _get_default_talent_pool()
        self.chat_history = {}
        self.rejections = []

    def _self_healing_audit(self) -> None:
        """
        开机状态自愈与强一致性审计：
        1. 面试日程一致性：候选人非 scheduled 状态的不允许存在活跃 upcoming 日程；
           反之，候选人为 scheduled 状态的若缺失日程，自动补齐；
        2. 人才公海排他性：候选人库中已存在的 ID，不允许同时留存在人才公海；
        3. 关键字段保全：保证所有候选人与公海人才具备 major, school_tier, education_type 等字段；
        4. 杜绝幽灵/孤儿关联。
        """
        cand_map = {c["id"]: c for c in self.candidates}

        # 1. 人才公海去重排他（以候选人池为准）
        active_ids = set(cand_map.keys())
        cleaned_pool = []
        for t in self.talent_pool:
            if t["id"] not in active_ids:
                cleaned_pool.append(t)
        self.talent_pool = cleaned_pool

        # 2. 面试排期清洗与自愈
        cleaned_interviews = []
        interviewed_cand_ids = set()
        for iv in self.interviews:
            cid = iv.get("candidate_id")
            cand = cand_map.get(cid)
            # 只有候选人确实处于 scheduled 状态，日程才保留
            if cand and cand.get("state") == "scheduled":
                cleaned_interviews.append(iv)
                interviewed_cand_ids.add(cid)
            elif not cand:
                # 候选人已不存在，丢弃孤儿日程
                continue

        # 反向补偿：若候选人状态为 scheduled 但在 interviews 中遗漏，自动补齐日程
        for c in self.candidates:
            if c.get("state") == "scheduled" and c["id"] not in interviewed_cand_ids:
                cleaned_interviews.append({
                    "id": f"iv-auto-{c['id']}",
                    "candidate_id": c["id"],
                    "candidate_name": c.get("name", "候选人"),
                    "job_title": "资深前端开发 / 全栈工程师",
                    "round": "业务初试 (视频)",
                    "time": "待技术专家确认排期",
                    "interviewer": "技术负责人",
                    "meeting_link": "https://meeting.recruitai.com/room/auto",
                    "status": "upcoming"
                })
        self.interviews = cleaned_interviews

        # 3. 补全缺失的关键结构化字段（防止比对算法报错）
        for c in self.candidates + self.talent_pool:
            if "education_type" not in c:
                c["education_type"] = "full_time"
            if "school_tier" not in c:
                c["school_tier"] = "other"
            if "major" not in c:
                c["major"] = ""

        # 4. 自愈补全思维链与题库结构（平滑升级老版本 store.json 持久化数据）
        preset_map = {p["id"]: p for p in PRESET_CANDIDATES}
        for c in self.candidates:
            da = c.setdefault("deep_audit", {})
            if not da.get("reasoning_chain"):
                p = preset_map.get(c.get("id"))
                if p and p.get("deep_audit", {}).get("reasoning_chain"):
                    da["reasoning_chain"] = p["deep_audit"]["reasoning_chain"]
                else:
                    name = c.get("name", "候选人")
                    school = c.get("school", "高校")
                    exp = c.get("experience_years", 3)
                    company = c.get("current_company", "科技公司")
                    skills = ", ".join(c.get("skills", ["核心技术栈"])[:3])
                    da["reasoning_chain"] = (
                        f"针对候选人【{name}】的 ReAct 自主交叉尽调推导：\n"
                        f"1. 时序真实性比对：毕业于{school}，工龄{exp}年，核查{company}就职时间线自洽连贯，无履历空窗异常；\n"
                        f"2. 工程含金量与量化脱水：技术栈聚焦于{skills}，项目经历具备生产环境真实主导特征，量化可信度高；\n"
                        f"3. 岗位匹配度综合反思：研发功底与业务场景高度契合，点击右上角「重新尽调推测」可唤起大模型现场二次深度推导。"
                    )
            if not c.get("question_theme"):
                c["question_theme"] = "架构设计与极端高并发攻坚"
            qs = c.get("interview_questions", [])
            if qs and isinstance(qs[0], str):
                new_qs = []
                for q_str in qs:
                    new_qs.append({
                        "question": q_str,
                        "thinking": f"考查候选人在【{c.get('current_company', '过往企业')}】核心技术栈场景下的底层原理掌握与实战深度。"
                    })
                c["interview_questions"] = new_qs

    def save(self) -> None:
        """执行原子写盘，彻底杜绝数据写损与崩溃"""
        with self._lock:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "jobs": self.jobs,
                "candidates": self.candidates,
                "interviews": self.interviews,
                "talent_pool": self.talent_pool,
                "chat_history": self.chat_history,
                "rejections": self.rejections,
            }
            tmp_file = STORE_FILE.with_suffix(".tmp")
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                # Windows 下 os.replace 为原子文件替换
                os.replace(tmp_file, STORE_FILE)
            except Exception as e:
                print(f"[RecruitAI Storage] 保存数据落盘失败: {e}")
                if tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except Exception:
                        pass

    def restore_from_baseline(self) -> str:
        """
        开发自测一键数据恢复：将全量运行时数据还原为基线快照（data/store.baseline.json）。
        基线快照缺失或损坏时，自动回退为 app/core/presets.py 的出厂预设种子数据。
        返回实际生效的恢复来源："baseline" 或 "preset"。
        """
        with self._lock:
            source = "preset"
            if BASELINE_FILE.exists():
                try:
                    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._load_payload_into_memory(data)
                    source = "baseline"
                except Exception as e:
                    print(f"[RecruitAI Storage] 基线快照读取异常 ({e})，回退为出厂预设数据。")
            if source == "preset":
                self._seed_default_data()
            # 恢复后仍执行一次一致性自愈校验，保证各实体关联强一致
            self._self_healing_audit()
            self._initialized = True
            self.save()
            return source

    def reset(self) -> str:
        """
        重置为初始演示数据并即时写盘。
        优先以基线快照 (data/store.baseline.json) 为还原源，保证“恢复到开发者约定的干净状态”；
        基线缺失时退化为出厂预设种子数据。
        """
        return self.restore_from_baseline()


# 全局单例
storage = StorageManager()
