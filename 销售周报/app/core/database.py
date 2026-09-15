"""
SalesAgent v2.0 · SQLite 数据持久化核心模块
提供线程安全、事务一致性的数据仓储层，保证周报台账、主管批阅、ReAct 尽调档案与决策内参在重启后 100% 完整留存。
"""
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from app.core.aggregator import (
    build_fallback_summary,
    calculate_team_metrics,
    FALLBACK_PERIOD,
    FALLBACK_TITLE,
)
from app.core.presets import PRESET_SALES_REPORTS

# 数据库文件路径: 存放于项目根目录下的 data/ 目录
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "sales_reports.db"

_db_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """获取启用了 WAL 模式的 SQLite 数据库连接"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=10.0,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _row_to_report(row: sqlite3.Row) -> Dict[str, Any]:
    """将 SQLite 行记录转换为业务周报字典，反序列化 JSON 字段"""
    d = dict(row)
    d["reviewed"] = bool(d.get("reviewed", 0))
    d["review_time"] = d.get("review_time") or ""
    d["supervisor_comment"] = d.get("supervisor_comment") or ""

    for json_col in ("hard_gate", "supervision_audit"):
        val = d.get(json_col)
        if val and isinstance(val, str):
            try:
                d[json_col] = json.loads(val)
            except Exception:
                d[json_col] = {}
        elif not val:
            d[json_col] = {}

    return d


def init_db() -> None:
    """
    幂等初始化数据库表结构与预设数据
    若 reports 表为空，自动在单一事务内播种标准 4 位销售代表及初始内参
    """
    with _db_lock:
        conn = get_connection()
        try:
            with conn:
                # 1. 销售周报明细台账表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS reports (
                        id TEXT PRIMARY KEY,
                        filename TEXT,
                        salesperson TEXT,
                        department TEXT,
                        role_title TEXT,
                        avatar_bg TEXT,
                        report_period TEXT DEFAULT '',
                        target_amount REAL DEFAULT 0.0,
                        actual_amount REAL DEFAULT 0.0,
                        collection_amount REAL DEFAULT 0.0,
                        completion_rate REAL DEFAULT 0.0,
                        visit_count INTEGER DEFAULT 0,
                        new_leads INTEGER DEFAULT 0,
                        status TEXT,
                        status_label TEXT,
                        highlight_summary TEXT,
                        blockers TEXT,
                        next_week_plan TEXT,
                        raw_content TEXT,
                        reviewed INTEGER DEFAULT 0,
                        supervisor_comment TEXT DEFAULT '',
                        review_time TEXT DEFAULT '',
                        hard_gate TEXT,
                        supervision_audit TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    );
                """)

                # 存量库迁移：补齐 report_period 列（早期版本无周期维度）
                cur = conn.execute("PRAGMA table_info(reports);")
                existing_cols = {row[1] for row in cur.fetchall()}
                if "report_period" not in existing_cols:
                    conn.execute("ALTER TABLE reports ADD COLUMN report_period TEXT DEFAULT '';")

                # 2. 销售部每周运营汇总与决策内参表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS summaries (
                        id TEXT PRIMARY KEY,
                        report_title TEXT,
                        cycle_period TEXT,
                        executive_overview TEXT,
                        highlights TEXT,
                        risk_radar TEXT,
                        manager_action_items TEXT,
                        updated_at TEXT
                    );
                """)

                # 3. 战区经营全景动态诊断推演缓存表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS diagnostics (
                        id TEXT PRIMARY KEY,
                        health_score INTEGER DEFAULT 60,
                        confidence_rate REAL DEFAULT 70.0,
                        risk_exposure INTEGER DEFAULT 0,
                        total_reps INTEGER DEFAULT 0,
                        high_confidence_count INTEGER DEFAULT 0,
                        at_risk_count INTEGER DEFAULT 0,
                        strategy_insights TEXT,
                        generated_at TEXT
                    );
                """)

                # 检查是否需要播种初始数据
                cur = conn.execute("SELECT COUNT(*) FROM reports;")
                count = cur.fetchone()[0]
                if count == 0:
                    _seed_presets_internal(conn)
        finally:
            conn.close()


def _seed_presets_internal(conn: sqlite3.Connection) -> None:
    """在现有打开连接中事务性播种初始预设数据"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 插入 4 位预设销售代表
    for r in PRESET_SALES_REPORTS:
        hard_gate_json = json.dumps(r.get("hard_gate", {}), ensure_ascii=False)
        supervision_json = json.dumps(r.get("supervision_audit", {}), ensure_ascii=False)
    conn.execute("""
        INSERT OR REPLACE INTO reports (
            id, filename, salesperson, department, role_title, avatar_bg, report_period,
            target_amount, actual_amount, collection_amount, completion_rate,
            visit_count, new_leads, status, status_label, highlight_summary,
            blockers, next_week_plan, raw_content, reviewed, supervisor_comment,
            review_time, hard_gate, supervision_audit, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        r.get("id"),
        r.get("filename", ""),
        r.get("salesperson", ""),
        r.get("department", ""),
        r.get("role_title", "客户经理"),
        r.get("avatar_bg", "bg-teal-600"),
        r.get("report_period", "2026年第36周"),
        float(r.get("target_amount", 0.0)),
            float(r.get("actual_amount", 0.0)),
            float(r.get("collection_amount", 0.0)),
            float(r.get("completion_rate", 0.0)),
            int(r.get("visit_count", 0)),
            int(r.get("new_leads", 0)),
            r.get("status", "on_track"),
            r.get("status_label", "稳步推进"),
            r.get("highlight_summary", ""),
            r.get("blockers", ""),
            r.get("next_week_plan", ""),
            r.get("raw_content", ""),
            1 if r.get("reviewed") else 0,
            r.get("supervisor_comment", ""),
            r.get("review_time", ""),
            hard_gate_json,
            supervision_json,
            now_str,
            now_str,
        ))

    # 2. 播种初始汇总内参
    metrics = calculate_team_metrics(PRESET_SALES_REPORTS)
    fallback_sum = build_fallback_summary(PRESET_SALES_REPORTS, metrics)
    conn.execute("""
        INSERT OR REPLACE INTO summaries (
            id, report_title, cycle_period, executive_overview,
            highlights, risk_radar, manager_action_items, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        "latest",
        fallback_sum.get("report_title", FALLBACK_TITLE),
        fallback_sum.get("cycle_period", FALLBACK_PERIOD),
        fallback_sum.get("executive_overview", ""),
        json.dumps(fallback_sum.get("highlights", []), ensure_ascii=False),
        json.dumps(fallback_sum.get("risk_radar", []), ensure_ascii=False),
        json.dumps(fallback_sum.get("manager_action_items", []), ensure_ascii=False),
        now_str,
    ))

    # 3. 播种初始战区动态诊断基线
    default_insights = [
        "【标杆战法复制】KA 大客户攻坚战役打法已被验证高可信，建议将其供应链协同与高层公关路径沉淀为标准打法，在华东、华北跨区推广。",
        "【卡单止血排雷】大盘存在 1 处重大卡点异动（北方清洁能源集团体制换届卡单），建议主管协同法务与高管下周亲自前往北京现场陪访破局。",
        "【商机蓄水扩容】华北大区过程拜访与新增线索存在下滑迹象，需强化商机蓄水池复盘，严防下月业绩断崖式下行。",
        "【高管资源协同】战略创新业务与新人团队拜访密度充沛，需加派总部技术专家与解决方案架构师给予售前资源兜底支持。"
    ]
    conn.execute("""
        INSERT OR REPLACE INTO diagnostics (
            id, health_score, confidence_rate, risk_exposure, total_reps,
            high_confidence_count, at_risk_count, strategy_insights, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        "latest",
        70,
        68.8,
        25,
        4,
        3,
        1,
        json.dumps(default_insights, ensure_ascii=False),
        now_str,
    ))


# ---------------------------------------------------------------------------
# 周报台账 (Reports) CRUD 操作
# ---------------------------------------------------------------------------

def get_all_reports() -> List[Dict[str, Any]]:
    """获取数据库中全部销售周报"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM reports ORDER BY actual_amount DESC;")
        rows = cur.fetchall()
        return [_row_to_report(r) for r in rows]
    finally:
        conn.close()


def get_report_by_id(report_id: str) -> Optional[Dict[str, Any]]:
    """根据 ID 获取单份销售周报"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM reports WHERE id = ?;", (report_id,))
        row = cur.fetchone()
        return _row_to_report(row) if row else None
    finally:
        conn.close()


def save_reports_batch(reports: List[Dict[str, Any]]) -> None:
    """批量插入或更新周报，具备原子性保证"""
    with _db_lock:
        conn = get_connection()
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with conn:
                for r in reports:
                    hard_gate_json = json.dumps(r.get("hard_gate", {}), ensure_ascii=False)
                    supervision_json = json.dumps(r.get("supervision_audit", {}), ensure_ascii=False)
                    conn.execute("""
                        INSERT OR REPLACE INTO reports (
                            id, filename, salesperson, department, role_title, avatar_bg, report_period,
                            target_amount, actual_amount, collection_amount, completion_rate,
                            visit_count, new_leads, status, status_label, highlight_summary,
                            blockers, next_week_plan, raw_content, reviewed, supervisor_comment,
                            review_time, hard_gate, supervision_audit, created_at, updated_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            COALESCE((SELECT created_at FROM reports WHERE id = ?), ?),
                            ?
                        );
                    """, (
                        r.get("id"),
                        r.get("filename", ""),
                        r.get("salesperson", ""),
                        r.get("department", ""),
                        r.get("role_title", "客户经理"),
                        r.get("avatar_bg", "bg-teal-600"),
                        r.get("report_period", ""),
                        float(r.get("target_amount", 0.0)),
                        float(r.get("actual_amount", 0.0)),
                        float(r.get("collection_amount", 0.0)),
                        float(r.get("completion_rate", 0.0)),
                        int(r.get("visit_count", 0)),
                        int(r.get("new_leads", 0)),
                        r.get("status", "on_track"),
                        r.get("status_label", "稳步推进"),
                        r.get("highlight_summary", ""),
                        r.get("blockers", ""),
                        r.get("next_week_plan", ""),
                        r.get("raw_content", ""),
                        1 if r.get("reviewed") else 0,
                        r.get("supervisor_comment", ""),
                        r.get("review_time", ""),
                        hard_gate_json,
                        supervision_json,
                        r.get("id"),
                        now_str,
                        now_str,
                    ))
        finally:
            conn.close()


def update_report_review(report_id: str, comment: str, review_time: str) -> Optional[Dict[str, Any]]:
    """原子更新单份周报的主管批阅状态与评语"""
    with _db_lock:
        conn = get_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE reports
                    SET reviewed = 1, supervisor_comment = ?, review_time = ?, updated_at = ?
                    WHERE id = ?;
                """, (comment, review_time, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), report_id))
            cur = conn.execute("SELECT * FROM reports WHERE id = ?;", (report_id,))
            row = cur.fetchone()
            return _row_to_report(row) if row else None
        finally:
            conn.close()


def update_report_audit(report_id: str, supervision_audit: Dict[str, Any], hard_gate: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """原子更新单份周报的 ReAct 智能体尽调档案与置信度"""
    with _db_lock:
        conn = get_connection()
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            audit_json = json.dumps(supervision_audit, ensure_ascii=False)
            with conn:
                if hard_gate is not None:
                    gate_json = json.dumps(hard_gate, ensure_ascii=False)
                    conn.execute("""
                        UPDATE reports
                        SET supervision_audit = ?, hard_gate = ?, updated_at = ?
                        WHERE id = ?;
                    """, (audit_json, gate_json, now_str, report_id))
                else:
                    conn.execute("""
                        UPDATE reports
                        SET supervision_audit = ?, updated_at = ?
                        WHERE id = ?;
                    """, (audit_json, now_str, report_id))
            cur = conn.execute("SELECT * FROM reports WHERE id = ?;", (report_id,))
            row = cur.fetchone()
            return _row_to_report(row) if row else None
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 决策内参 (Summaries) CRUD 操作
# ---------------------------------------------------------------------------

def get_latest_summary() -> Dict[str, Any]:
    """获取持久化的运营内参；若无则根据当前 reports 实时构建兜底内参"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM summaries WHERE id = 'latest';")
        row = cur.fetchone()
        if row:
            d = dict(row)
            for json_col in ("highlights", "risk_radar", "manager_action_items"):
                val = d.get(json_col)
                if val and isinstance(val, str):
                    try:
                        d[json_col] = json.loads(val)
                    except Exception:
                        d[json_col] = []
                elif not val:
                    d[json_col] = []
            return d
    finally:
        conn.close()

    # 兜底构建
    reports = get_all_reports()
    metrics = calculate_team_metrics(reports)
    fallback = build_fallback_summary(reports, metrics)
    save_summary(fallback)
    return fallback


def save_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """持久化保存最新运营内参"""
    with _db_lock:
        conn = get_connection()
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            hl_json = json.dumps(summary.get("highlights", []), ensure_ascii=False)
            radar_json = json.dumps(summary.get("risk_radar", []), ensure_ascii=False)
            action_json = json.dumps(summary.get("manager_action_items", []), ensure_ascii=False)

            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO summaries (
                        id, report_title, cycle_period, executive_overview,
                        highlights, risk_radar, manager_action_items, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    "latest",
                    summary.get("report_title", FALLBACK_TITLE),
                    summary.get("cycle_period", FALLBACK_PERIOD),
                    summary.get("executive_overview", ""),
                    hl_json,
                    radar_json,
                    action_json,
                    now_str,
                ))
            return get_latest_summary()
        finally:
            conn.close()


def sync_summary_on_upload(new_reports_count: int) -> None:
    """
    当上传新周报时，联动刷新内参大盘述评数字，保持文本与最新指标绝对闭环同步
    """
    reports = get_all_reports()
    metrics = calculate_team_metrics(reports)
    current_sum = get_latest_summary()

    # 重新构建与当前实际人数和签约额严格吻合的述评
    fresh_sum = build_fallback_summary(reports, metrics)
    current_sum["executive_overview"] = fresh_sum["executive_overview"]
    current_sum["highlights"] = fresh_sum["highlights"]
    current_sum["risk_radar"] = fresh_sum["risk_radar"]
    current_sum["manager_action_items"] = fresh_sum["manager_action_items"]

    save_summary(current_sum)


# ---------------------------------------------------------------------------
# 战区动态诊断 (Diagnostics) CRUD 操作
# ---------------------------------------------------------------------------

def get_latest_diagnostics() -> Optional[Dict[str, Any]]:
    """获取持久化的战区全景动态诊断推演"""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM diagnostics WHERE id = 'latest';")
        row = cur.fetchone()
        if row:
            d = dict(row)
            val = d.get("strategy_insights")
            if val and isinstance(val, str):
                try:
                    d["strategy_insights"] = json.loads(val)
                except Exception:
                    d["strategy_insights"] = []
            elif not val:
                d["strategy_insights"] = []
            return d
        return None
    finally:
        conn.close()


def save_diagnostics(diag: Dict[str, Any]) -> None:
    """持久化保存最新动态推演诊断"""
    with _db_lock:
        conn = get_connection()
        try:
            insights_json = json.dumps(diag.get("strategy_insights", []), ensure_ascii=False)
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO diagnostics (
                        id, health_score, confidence_rate, risk_exposure, total_reps,
                        high_confidence_count, at_risk_count, strategy_insights, generated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    "latest",
                    diag.get("health_score", 60),
                    diag.get("confidence_rate", 70.0),
                    diag.get("risk_exposure", 0),
                    diag.get("total_reps", 0),
                    diag.get("high_confidence_count", 0),
                    diag.get("at_risk_count", 0),
                    insights_json,
                    diag.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                ))
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 单事务级联原子重置 (Atomic Cascade Reset)
# ---------------------------------------------------------------------------

def reset_to_presets() -> int:
    """
    单事务级联清空并重置全部三表，100% 恢复洁净初始态，杜绝孤儿数据
    """
    with _db_lock:
        conn = get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM reports;")
                conn.execute("DELETE FROM summaries;")
                conn.execute("DELETE FROM diagnostics;")
                _seed_presets_internal(conn)
            cur = conn.execute("SELECT COUNT(*) FROM reports;")
            return cur.fetchone()[0]
        finally:
            conn.close()
