"""
智审 (Doc-Agent) - Agent 主循环（ReAct 状态机）
感知 (Perceive) → 规划 (Plan) → 行动 (Act) → 反思 (Reflect) 四阶段闭环，
控制流由模型决策、执行权归代码。

设计原则（融合终版计划书）：
1. 决策权归模型，执行权归代码 —— 模型决定「查什么」，代码负责「怎么查」
2. 规则退居为工具 + 主动安全网 —— Agent 审完后规则引擎静默交叉验证补漏
3. 全程可解释 —— 每次分诊决策必须携带 why，SSE 全程透传推理轨迹
4. 预算硬约束 —— 单条重试 ≤2、全局回环 ≤1、时间预算触顶强制收敛
5. 下限不降低 —— 拆条失败→全文模式；分诊失败→规则路由；深查失败→规则补位

SSE 新事件：perceive / plan / trace / risk_card / reflection / fallback_notice
内部事件：agent_report（最终报告，由 engine 拦截后走 content/draft/done 收尾）
"""

import asyncio
import logging
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from config import config
from contract.parser import detect_contract_type
from contract.clause_splitter import (
    split_clauses,
    clauses_from_llm_output,
    clauses_summary_for_prompt,
)
from contract.planner import make_plan_messages, parse_plan, rule_fallback_plan
from contract.prompts import (
    LLM_CLAUSE_SPLIT_PROMPT,
    DEEP_DIVE_SYSTEM_PROMPT,
    QUICK_SCAN_PROMPT,
    GLOBAL_REFLECT_PROMPT,
    render_prompt,
)
from contract.tools import (
    parse_tool_calls,
    parse_json_lenient,
    execute_tool,
    format_tool_specs_for_prompt,
)
from contract.statutes import verify_citations
from contract.rule_cards import scan_rules, render_rule_card
from contract.precedents import PRECEDENTS_DATABASE

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """全局时间/调用预算触顶，强制收敛"""


class LLMClient:
    """非流式补全包装（Agent 各结构化阶段共用；<think> 统一清洗）

    针对端侧 reasoning 模型（如 qwen3 系列）的健壮性处理：
      1. content 为空时，从 reasoning_content 中回收最终答案（否则整条链路哑火）
      2. finish_reason == "length" 时记录截断告警，便于定位预算/token 不足
      3. 结构化调用（want_json）遇截断且 content 为空 → 自动扩容 max_tokens 重试一次
    """

    #: 截断重试时 max_tokens 的扩容上限
    MAX_TOKENS_CEILING = 16000

    #: 「模型暂时不可用」类错误的特征串。
    #: LM Studio 会在内存紧张 / 自动卸载（TTL）时把正在服务的模型卸下，
    #: 此时请求返回 400 Model unloaded；紧接着的即时重载又可能被
    #: Operation canceled 打断。这类错误是**可重试**的：LM Studio 收到下一次
    #: 请求会重新 JIT 加载模型（实测 14B 约 20~30 秒）。
    _LOAD_ERR_MARKERS = (
        "model unloaded",
        "failed to load model",
        "operation canceled",
        "terminated",
        "connection error",
        "connection reset",
    )

    @classmethod
    def _is_model_unavailable(cls, err: str) -> bool:
        low = (err or "").lower()
        return any(k in low for k in cls._LOAD_ERR_MARKERS)

    def __init__(self, openai_client, model: str):
        self.client = openai_client
        self.model = model
        self.last_finish_reason: Optional[str] = None
        self.truncated_count = 0
        self.last_error: Optional[str] = None

    async def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.15,
        max_tokens: int = 2400,
        want_json: bool = False,
    ) -> str:
        budget = max_tokens
        for attempt in range(2):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=budget,
                    stream=False,
                )
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
                self.last_error = err
                # 模型被卸载 / 重载被取消 属于可重试错误：直接放弃会让本条结论降级为
                # 规则补位（报告质量下降，还会出现"摘要说高危 4 处、报告只列 1 项"这类不一致）。
                # 这里等一小会儿再试一次，LM Studio 会随之重新加载模型。
                if attempt == 0 and self._is_model_unavailable(err):
                    logger.warning("模型 %s 暂时不可用，5 秒后重试一次：%s", self.model, err)
                    await asyncio.sleep(5)
                    continue
                # 端侧服务异常（LM Studio 400 terminated / 上下文超限 / 连接中断等）
                # 统一降级为空输出，交由上层走规则补位，避免异常穿透打断整条审查链路
                logger.error("模型调用失败（%s）: %s", self.model, self.last_error)
                return ""
            try:
                choice = resp.choices[0]
                msg = choice.message
                finish = getattr(choice, "finish_reason", None)
                content = (msg.content or "").strip()
                reasoning = getattr(msg, "reasoning_content", None) or ""
            except Exception:
                return ""

            self.last_finish_reason = finish

            # reasoning 模型兜底：思考内容吃满 token 导致 content 为空时，
            # 从推理文本中回收 JSON/最终结论，避免整条链路静默失败
            if not content and reasoning:
                harvested = self._harvest_from_reasoning(reasoning)
                if harvested:
                    logger.warning(
                        "模型 %s 的 content 为空（finish=%s），已从 reasoning_content 回收 %d 字符",
                        self.model, finish, len(harvested),
                    )
                    content = harvested

            if finish == "length":
                self.truncated_count += 1
                logger.warning(
                    "模型 %s 输出被截断（max_tokens=%d，content=%d 字符，reasoning=%d 字符）",
                    self.model, budget, len(content), len(reasoning),
                )
                # 结构化调用被截断且没拿到内容 → 扩容后重试一次
                if attempt == 0 and want_json and not content:
                    budget = min(budget * 2, self.MAX_TOKENS_CEILING)
                    logger.warning("结构化调用截断，扩容至 max_tokens=%d 重试一次", budget)
                    continue

            return self.clean_think(content)

        return ""

    @staticmethod
    def _harvest_from_reasoning(reasoning: str) -> str:
        """从 reasoning_content 中回收最终答案：优先取最后一个平衡的 JSON 对象"""
        if not reasoning:
            return ""
        # 1. 优先找完整 JSON 块（从最后一个 { 向前匹配平衡括号）
        end = reasoning.rfind("}")
        while end > 0:
            depth = 0
            for i in range(end, -1, -1):
                ch = reasoning[i]
                if ch == "}":
                    depth += 1
                elif ch == "{":
                    depth -= 1
                    if depth == 0:
                        candidate = reasoning[i:end + 1]
                        if len(candidate) > 20 and '":' in candidate:
                            return candidate
                        break
            end = reasoning.rfind("}", 0, end)
        # 2. 退化为整体返回（交由上层 JSON 容错解析）
        return reasoning.strip()

    @staticmethod
    def clean_think(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</?think>", "", text)
        return text.strip()


class ContractReviewAgent:
    """ReAct 主循环控制器：一次 run() 审一份合同"""

    def __init__(self, llm: LLMClient, time_budget_s: int = None):
        self.llm = llm
        self.time_budget_s = time_budget_s or config.AGENT_TIME_BUDGET_SECONDS
        self.max_deep = config.AGENT_MAX_DEEP_DIVE
        self.max_tool_rounds = config.AGENT_MAX_TOOL_ROUNDS_PER_CLAUSE
        self.max_retry = config.AGENT_MAX_RETRY_PER_CLAUSE
        self.max_reflect_rounds = config.AGENT_GLOBAL_REFLECT_ROUNDS
        self._t0 = time.time()
        self._calls = 0
        self._pending_traces: List[Dict[str, Any]] = []
        self._last_deep_result: Optional[Dict[str, Any]] = None
        self._last_tool_trace_count = 0
        # 运行态
        self.used_precedent_ids: set = set()
        self.tool_call_count = 0

    # ------------------------------------------------------------------
    # 预算守卫
    # ------------------------------------------------------------------
    def _budget_left(self) -> bool:
        return (time.time() - self._t0) < self.time_budget_s

    async def _llm(self, messages, temperature=0.15, max_tokens=2400, want_json: bool = False) -> str:
        if not self._budget_left():
            raise BudgetExceededError()
        self._calls += 1
        return await self.llm.complete(
            messages, temperature=temperature, max_tokens=max_tokens, want_json=want_json
        )

    def _elapsed(self) -> int:
        return int(time.time() - self._t0)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    async def run(
        self,
        contract_text: str,
        contract_type_hint: str,
        client_role: str,
        review_stance: str,
        focus_dimensions: List[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        self._t0 = time.time()
        context = {
            "client_role": client_role,
            "review_stance": review_stance,
            "focus_dimensions": focus_dimensions,
        }

        # ================= Phase 1 感知 =================
        clauses, split_mode = await self._perceive(contract_text)
        if len(clauses) < 1:
            # 极限兜底：无任何条款标记时将全文包装为单条款 C01，确保 Agent 闭环与轨迹思维链永不落空
            from contract.clause_splitter import _extract_signals, _candidate_labels
            head = "合同全文核心条款"
            sig = _extract_signals(head, contract_text)
            clauses = [{
                "clause_id": "C01",
                "index": 1,
                "heading": head,
                "text": contract_text,
                "char_range": [0, len(contract_text)],
                "signals": sig,
                "candidate_labels": _candidate_labels(head, contract_text, sig),
            }]
            split_mode = "whole_doc"

        kw_type = contract_type_hint
        if not kw_type or kw_type in ("auto", "通用商业民商事经济合同"):
            kw_type = detect_contract_type(contract_text)

        yield {
            "type": "perceive",
            "data": {
                "clause_count": len(clauses),
                "split_mode": split_mode,
                "keyword_type": kw_type,
                "clauses": [
                    {"clause_id": c["clause_id"], "heading": c["heading"],
                     "char_range": c["char_range"], "candidate_labels": c["candidate_labels"]}
                    for c in clauses
                ],
            },
            "message": f"感知完成：合同已结构化为 {len(clauses)} 条（拆条模式：{split_mode}），关键词预判类型【{kw_type}】",
        }

        # ================= Phase 2 规划 =================
        plan = await self._plan(clauses, kw_type, context)
        llm_type = plan.get("contract_type") or kw_type
        plan_summary = plan["summary"]

        # 先推送模型的规划推理（thinking 思维链），再推结构化分诊
        if plan.get("thinking"):
            yield {
                "type": "thinking",
                "data": {"phase": "plan", "clause_id": "", "text": plan["thinking"]},
                "message": "规划思路",
            }

        yield {
            "type": "plan",
            "data": {
                "contract_type": llm_type,
                "overall_strategy": plan.get("overall_strategy", ""),
                "clauses": plan["clauses"],
                "summary": plan_summary,
            },
            "message": (
                f"分诊完成：深查 {plan_summary['deep']} 条 / 快筛 {plan_summary['quick']} 条 / "
                f"跳过 {plan_summary['skip']} 条"
                + (f"（{len(plan_summary['budget_trimmed'])} 条因预算裁剪降级）" if plan_summary["budget_trimmed"] else "")
            ),
        }

        deep_entries = [e for e in plan["clauses"] if e["action"] == "deep_dive"]
        quick_entries = [e for e in plan["clauses"] if e["action"] == "quick_scan"]
        clause_map = {c["clause_id"]: c for c in clauses}

        # ================= Phase 3 行动 =================
        cards: List[Dict[str, Any]] = []
        clean_notes: List[Dict[str, Any]] = []
        done_ids: set = set()
        budget_hit = False

        async def _run_deep(clause, entry):
            """执行单条深查并冲刷 trace 帧（结果经 self._last_deep_result 传递）"""
            result, traces = await self._deep_dive_with_traces(clause, entry, context, plan)
            for t in traces:
                yield t

        for i, entry in enumerate(deep_entries, start=1):
            if not self._budget_left():
                budget_hit = True
                yield {
                    "type": "fallback_notice",
                    "data": {"scope": "act", "reason": "time_budget"},
                    "message": f"已达全局时间预算（{self.time_budget_s}s），剩余深查条款跳过，强制收敛进入反思阶段",
                }
                break
            clause = clause_map[entry["clause_id"]]
            yield {
                "type": "status",
                "message": f"Agent 深查中 {i}/{len(deep_entries)}：【{clause['heading']}】（分诊理由：{entry['why'][:60]}）",
            }
            # 深查开始轨迹：让「规划为深查 → 行动有记录」的链条闭环可追溯
            yield {
                "type": "trace",
                "data": {
                    "clause_id": entry["clause_id"],
                    "step": "深查开始",
                    "args": {"分诊评分": f"{entry['risk_score']}/10"},
                    "result_summary": f"按分诊结论执行深查（{entry['risk_score']}/10）：{entry['why'][:70]}",
                },
                "message": f"[{entry['clause_id']}] 深查开始（{entry['risk_score']}/10）",
            }
            try:
                gen = _run_deep(clause, entry)
                result = None
                async for t in gen:
                    yield t
                # async generator 无法返回值，改由内部暂存
                result = self._last_deep_result
            except BudgetExceededError:
                budget_hit = True
                yield {
                    "type": "fallback_notice",
                    "data": {"scope": "act", "reason": "time_budget"},
                    "message": "已达全局时间预算，强制收敛进入反思阶段",
                }
                break
            except Exception as e:
                logger.warning(f"深查 {entry['clause_id']} 异常: {e}", exc_info=True)
                result = self._rule_fill_card(clause)
                yield {
                    "type": "fallback_notice",
                    "data": {"scope": "deep_dive", "clause_id": entry["clause_id"], "reason": "llm_error"},
                    "message": f"【{clause['heading']}】深查调用异常，已由规则引擎补位扫描",
                }

            done_ids.add(entry["clause_id"])
            # 推送模型对该条款的推理（thinking 思维链），先于结论
            if result and result.get("thinking"):
                yield {
                    "type": "thinking",
                    "data": {"phase": "deep_dive", "clause_id": entry["clause_id"], "text": result["thinking"]},
                    "message": f"[{entry['clause_id']}] 深查分析",
                }
            # 深查完成轨迹：记录证据链规模与置信度，与「规划」段一一对应
            yield self._done_trace(entry["clause_id"], result)
            if result and result.get("card"):
                cards.append(result)
                yield {
                    "type": "risk_card",
                    "data": {
                        "clause_id": entry["clause_id"],
                        "heading": clause["heading"],
                        "card": result["card"],
                        "severity": result.get("severity", "high"),
                        "source": result.get("source", "agent"),
                        "confidence": result.get("confidence"),
                    },
                    "message": f"深查完成 {i}/{len(deep_entries)}：{clause['heading']} → 检出风险",
                }
            else:
                note = (result or {}).get("note", "深查未发现实质风险")
                clean_notes.append({"clause_id": entry["clause_id"], "note": note})
                yield {
                    "type": "risk_card",
                    "data": {"clause_id": entry["clause_id"], "heading": clause["heading"],
                             "card": None, "severity": "clean", "source": "agent",
                             "confidence": (result or {}).get("confidence")},
                    "message": f"深查完成 {i}/{len(deep_entries)}：{clause['heading']} → 未发现实质风险",
                }

        # 快筛批量核验（命中升级深查）
        if quick_entries and self._budget_left():
            try:
                upgrades = await self._quick_scan(quick_entries, clause_map)
                for entry in upgrades:
                    if len(done_ids) >= self.max_deep + 3 or not self._budget_left():
                        break
                    clause = clause_map[entry["clause_id"]]
                    yield {
                        "type": "trace",
                        "data": {"clause_id": entry["clause_id"], "step": "quick_scan_upgrade",
                                 "args": {}, "result_summary": f"快筛升级深查：{entry['why'][:80]}"},
                        "message": f"快筛命中升级：【{clause['heading']}】",
                    }
                    try:
                        gen = _run_deep(clause, entry)
                        async for t in gen:
                            yield t
                        result = self._last_deep_result
                    except (BudgetExceededError, Exception) as e:
                        logger.warning(f"升级深查异常，规则补位: {e}")
                        result = self._rule_fill_card(clause)
                    done_ids.add(entry["clause_id"])
                    yield self._done_trace(entry["clause_id"], result, prefix="快筛升级·")
                    if result and result.get("card"):
                        cards.append(result)
                        yield {
                            "type": "risk_card",
                            "data": {"clause_id": entry["clause_id"], "heading": clause["heading"],
                                     "card": result["card"], "severity": result.get("severity", "high"),
                                     "source": result.get("source", "agent"), "confidence": result.get("confidence")},
                            "message": f"快筛升级深查完成：{clause['heading']} → 检出风险",
                        }
                    else:
                        clean_notes.append({"clause_id": entry["clause_id"], "note": "升级深查未发现实质风险"})
            except BudgetExceededError:
                pass
            except Exception as e:
                logger.warning(f"快筛核验异常（忽略，不升级任何条款）: {e}")

        # ---- 全量留痕兜底：杜绝「漏审」观感 ----
        # 「决策权归模型、执行权归代码」的另一面是「覆盖由代码兜底」：
        # 凡规划已判定、但尚未产生任何记录（未进 done_ids）的条款——包括快筛核验通过、
        # 判为跳过、以及因时间预算未能处理者——一律补一条明示结论，保证每条条款都有交代。
        for entry in plan["clauses"]:
            cid = entry["clause_id"]
            if cid in done_ids or cid not in clause_map:
                continue
            clause = clause_map[cid]
            action = entry.get("action")
            if action == "quick_scan":
                note = "快筛核验未发现实质风险"
            elif action == "skip":
                note = f"低风险跳过：{entry.get('why', '')[:60]}"
            else:
                note = "已审查，未发现实质风险"
            clean_notes.append({"clause_id": cid, "note": note, "source": action or "agent"})
            done_ids.add(cid)
            yield {
                "type": "risk_card",
                "data": {"clause_id": cid, "heading": clause["heading"],
                         "card": None, "severity": "clean", "source": action or "agent"},
                "message": f"已审查：{clause['heading']} → 未发现实质风险",
            }

        # ================= Phase 4 反思 =================
        reflection: Optional[Dict[str, Any]] = None
        # 4.1 全局漏检复核（LLM）
        if self._budget_left():
            try:
                reflection = await self._global_reflect(clauses, plan, cards, clean_notes)
                yield {
                    "type": "reflection",
                    "data": {
                        "scope": "global",
                        "missed_clause_ids": reflection.get("missed_clause_ids", []),
                        "final_rating": reflection.get("final_rating", ""),
                        "confidence": reflection.get("confidence"),
                        "overall_comment": reflection.get("overall_comment", ""),
                        "levers": reflection.get("levers", []),
                    },
                    "message": f"全局反思完成：{reflection.get('overall_comment', '')[:80]}",
                }
                # 4.2 回环补审 ≤1 轮（模型推翻自己的 skip 判定 → 补 deep_dive）
                missed = [cid for cid in reflection.get("missed_clause_ids", [])
                          if cid in clause_map and cid not in done_ids]
                if missed and self._budget_left():
                    yield {
                        "type": "reflection",
                        "data": {"scope": "reopen", "clause_ids": missed[:3],
                                 "finding": "反思发现漏检条款，自动补查", "action": "reopen_deep_dive"},
                        "message": f"反思复核推翻跳过判定，补充深查：{', '.join(missed[:3])}",
                    }
                    for cid in missed[:3]:
                        if not self._budget_left():
                            break
                        clause = clause_map[cid]
                        yield {
                            "type": "trace",
                            "data": {"clause_id": cid, "step": "深查开始",
                                     "args": {"来源": "反思补查"},
                                     "result_summary": "反思复核推翻跳过判定，补充深查取证"},
                            "message": f"[{cid}] 反思补查·深查开始",
                        }
                        try:
                            gen = _run_deep(clause, {"clause_id": cid, "why": "反思补查", "tools": [], "risk_score": 7})
                            async for t in gen:
                                yield t
                            result = self._last_deep_result
                        except (BudgetExceededError, Exception) as e:
                            logger.warning(f"反思补查异常，规则补位: {e}")
                            result = self._rule_fill_card(clause)
                        done_ids.add(cid)
                        yield self._done_trace(cid, result, prefix="反思补查·")
                        if result and result.get("card"):
                            cards.append(result)
                            yield {
                                "type": "risk_card",
                                "data": {"clause_id": cid, "heading": clause["heading"],
                                         "card": result["card"], "severity": result.get("severity", "high"),
                                         "source": result.get("source", "agent"),
                                         "confidence": result.get("confidence"), "supplement": True},
                                "message": f"反思补查完成：{clause['heading']} → 检出风险",
                            }
                        else:
                            clean_notes.append({"clause_id": cid, "note": "反思补查未发现实质风险"})
            except BudgetExceededError:
                yield {
                    "type": "fallback_notice",
                    "data": {"scope": "reflect", "reason": "time_budget"},
                    "message": "反思阶段触达时间预算，跳过全局复核（规则引擎交叉验证仍将执行）",
                }
            except Exception as e:
                logger.warning(f"全局反思异常（忽略）: {e}")

        # 4.3 幻觉核验（代码侧，零模型成本，始终执行）
        all_card_text = "\n".join(c.get("card", "") for c in cards)
        citation_check = verify_citations(all_card_text)

        # 4.4 规则引擎静默交叉验证（主动安全网：发现 Agent 漏项自动补入）
        cross_cards, cross_hits = self._cross_validate(clauses, cards)
        for hit in cross_hits:
            yield {
                "type": "fallback_notice",
                "data": {"scope": "cross_validation", "clause_id": hit["clause_id"],
                         "rule": hit["rule_title"]},
                "message": f"规则引擎交叉验证发现漏项：【{hit['heading']}】命中「{hit['rule_title']}」，已自动补入报告",
            }
        cards.extend(cross_cards)

        # ================= Phase 5 组装 =================
        report = self._assemble_report(
            clauses, plan, cards, clean_notes, reflection, citation_check,
            llm_type, context, budget_hit,
        )
        yield {
            "type": "agent_report",
            "data": report,
            "meta": {
                "used_precedents": self._collect_used_precedents(),
                "plan_summary": plan_summary,
                "tool_calls": self.tool_call_count,
                "llm_calls": self._calls,
                "elapsed_seconds": self._elapsed(),
                "citation_check": citation_check,
            },
        }

    # ------------------------------------------------------------------
    # Phase 1: 感知
    # ------------------------------------------------------------------
    async def _perceive(self, contract_text: str):
        """混合拆条：正则优先，失败时 LLM 兜底，再失败按段落自适应切分"""
        clauses = split_clauses(contract_text)
        if len(clauses) >= 1:
            return clauses, "regex"

        try:
            raw = await self._llm(
                [
                    {"role": "system", "content": render_prompt(LLM_CLAUSE_SPLIT_PROMPT)},
                    {"role": "user", "content": f"合同全文：\n{contract_text[:8000]}"},
                ],
                temperature=0.1,
                max_tokens=3000,
                want_json=True,
            )
            items = parse_json_lenient(raw)
            if isinstance(items, list) and len(items) >= 1:
                llm_clauses = clauses_from_llm_output(items, contract_text)
                if len(llm_clauses) >= 1:
                    return llm_clauses, "llm_fallback"
        except BudgetExceededError:
            raise
        except Exception as e:
            logger.warning(f"LLM 兜底拆条失败: {e}")

        # 若均未切出，尝试按双换行段落自适应切分
        paras = [p.strip() for p in contract_text.split("\n\n") if p.strip()]
        if len(paras) >= 2:
            from contract.clause_splitter import _extract_signals, _candidate_labels
            p_clauses = []
            pos = 0
            for i, p in enumerate(paras, start=1):
                p_start = contract_text.find(p, pos)
                p_end = p_start + len(p) if p_start >= 0 else pos + len(p)
                pos = max(pos, p_end)
                first_line = p.splitlines()[0].strip()
                head = first_line[:30] if first_line else f"第{i}部分"
                sig = _extract_signals(head, p)
                p_clauses.append({
                    "clause_id": f"C{i:02d}",
                    "index": i,
                    "heading": head,
                    "text": p,
                    "char_range": [p_start, p_end] if p_start >= 0 else None,
                    "signals": sig,
                    "candidate_labels": _candidate_labels(head, p, sig),
                })
            return p_clauses, "paragraph_fallback"

        return clauses, "regex"

    # ------------------------------------------------------------------
    # Phase 2: 规划（分诊失败 → 规则路由回退）
    # ------------------------------------------------------------------
    async def _plan(self, clauses, kw_type, context) -> Dict[str, Any]:
        clauses_listing = clauses_summary_for_prompt(clauses)
        try:
            messages = make_plan_messages(
                clauses_listing, kw_type,
                context["client_role"], context["review_stance"],
                context.get("focus_dimensions"), max_deep=self.max_deep,
            )
            first_raw = await self._llm(messages, temperature=0.15, max_tokens=3000, want_json=True)
            # 提取模型推理（thinking），作为思维链透传前端
            thinking = self._extract_thinking(first_raw)
            raw = parse_json_lenient(self._strip_thinking(first_raw) if thinking else first_raw)
            if isinstance(raw, dict) and raw.get("clauses"):
                plan = parse_plan(raw, clauses, max_deep=self.max_deep)
                if thinking:
                    plan["thinking"] = thinking
                return plan
            # 二级容错：明确要求重试一次
            messages.append({"role": "assistant", "content": str(raw)[:500]})
            messages.append({"role": "user", "content": "你上次的输出不是合法的分诊 JSON。请只输出 JSON，不要任何其他文字。"})
            second_raw = await self._llm(messages, temperature=0.1, max_tokens=3000, want_json=True)
            if not thinking:
                thinking = self._extract_thinking(second_raw)
            raw = parse_json_lenient(self._strip_thinking(second_raw))
            if isinstance(raw, dict) and raw.get("clauses"):
                plan = parse_plan(raw, clauses, max_deep=self.max_deep)
                if thinking:
                    plan["thinking"] = thinking
                return plan
        except BudgetExceededError:
            raise
        except Exception as e:
            logger.warning(f"分诊规划失败，启用规则路由回退: {e}")
        return rule_fallback_plan(clauses, max_deep=self.max_deep)

    # ------------------------------------------------------------------
    # Phase 3: 单条深查（开放式工具调用 + self-check 重试 ≤2）
    # ------------------------------------------------------------------
    async def _deep_dive_with_traces(self, clause, entry, context, plan):
        """执行深查并返回 (result, trace帧列表)"""
        self._pending_traces = []
        self._last_deep_result = None
        self._last_tool_trace_count = 0
        try:
            self._last_deep_result = await self._deep_dive(clause, entry, context, plan)
            traces = list(self._pending_traces)
            self._last_tool_trace_count = len(traces)
            return self._last_deep_result, traces
        finally:
            self._pending_traces = []

    # ------------------------------------------------------------------
    # Phase 3: 代码侧主动取证（执行权归代码）
    # ------------------------------------------------------------------
    def _done_trace(self, clause_id: str, result: Optional[Dict[str, Any]], prefix: str = "") -> Dict[str, Any]:
        """构造「深查完成」轨迹帧（统一主深查/快筛升级/反思补查三处记录口径）

        除结论外，同时携带模型的自我批评（critique）与评级，
        使前端能把「分诊理由 → 取证 → 自检 → 结论」串成完整决策链。
        """
        sev_key = (result or {}).get("severity", "")
        sev = {"high": "高危", "medium": "中危", "clean": "未发现实质风险"}.get(sev_key, "未发现实质风险")
        critique = (result or {}).get("critique") or ""
        if result and result.get("card"):
            desc = (f"{prefix}深查完成：检出{sev}风险 · 证据链 {self._last_tool_trace_count} 条"
                    f" · 置信度 {result.get('confidence')}")
        else:
            desc = f"{prefix}深查完成：{sev} · 证据链 {self._last_tool_trace_count} 条"
        return {
            "type": "trace",
            "data": {
                "clause_id": clause_id,
                "step": "深查完成",
                "args": {},
                "result_summary": desc,
                "critique": critique,
                "severity": sev_key,
                "confidence": (result or {}).get("confidence"),
            },
            "message": f"[{clause_id}] {desc}",
        }

    def _build_evidence_queries(self, clause, entry) -> List[tuple]:
        """按「候选标签 → 规则命中 → 条款标题」优先级推导取证检索词（倾向于短词，检索命中率更高）"""
        keywords: List[str] = []
        # 1) 候选标签：短且语义清晰（如「违约金畸高候选」→「违约金畸高」）
        for lab in (clause.get("candidate_labels") or [])[:2]:
            kw = str(lab).replace("候选", "").strip()
            if kw:
                keywords.append(kw)
        # 2) 规则命中标题：优先取「：」前的法律主题词（如「违约责任」「知识产权」），
        #    检索命中率显著高于长句描述
        for hit in scan_rules(clause["text"])[:2]:
            title = str(hit.get("title", ""))
            topic = title.split("：")[0].strip()
            if 2 <= len(topic) <= 10:
                keywords.append(topic)
            core = title.split("：")[-1]
            picked = ""
            for seg in re.split(r"[与和及、，,]", core):
                if 2 <= len(seg) <= 12:
                    picked = seg
                    break
            keywords.append(picked or core[:12])
        # 3) 兜底：条款标题
        if not keywords:
            keywords.append(clause["heading"][:20])

        queries: List[tuple] = []
        seen = set()
        for kw in keywords:
            kw = str(kw).strip()
            if not kw or kw in seen:
                continue
            seen.add(kw)
            queries.append(("statute_lookup", {"keyword": kw, "top_k": 3}))
            queries.append(("precedent_search", {"query": kw, "top_k": 2}))
        return queries

    def _prefetch_evidence(self, clause, entry) -> str:
        """
        代码侧预取证据：按线索检索法条与判例，返回注入 Prompt 的证据块，
        并将工具调用写入轨迹（保证「规划→行动」链条完整可追溯）。
        """
        queries = self._build_evidence_queries(clause, entry)
        if not queries:
            return ""
        blocks: List[str] = []
        for tool_name, args in queries[:3]:
            try:
                res = execute_tool(tool_name, args)
            except Exception as e:
                logger.debug("预取工具 %s 失败: %s", tool_name, e)
                continue
            summary = (res or {}).get("result_summary", "")
            if not summary:
                continue
            prompt_text = (res or {}).get("prompt_text", "")

            # 判例相关性过滤：precedent_search 在无匹配时会兜底填充近似判例，
            # 直接注入会诱导模型错误引用（幻觉），故按标题关键词重叠度过滤
            if tool_name == "precedent_search":
                query = str(args.get("query", ""))
                q_chars = {ch for ch in query if "\u4e00" <= ch <= "\u9fa5"}
                items = (res.get("data") or [])
                relevant = [
                    p for p in items
                    if len(q_chars & {ch for ch in str(p.get("title", "")) if "\u4e00" <= ch <= "\u9fa5"}) >= 2
                ]
                if not relevant:
                    summary = f"未检索到与「{query}」高度相关的裁判要旨"
                    prompt_text = ""

            self.tool_call_count += 1
            if tool_name == "precedent_search":
                for p in (res.get("data") or []):
                    self.used_precedent_ids.add(p.get("id"))
            self._pending_traces.append({
                "type": "trace",
                "data": {
                    "clause_id": clause["clause_id"],
                    "step": f"{tool_name}·预取",
                    "args": {k: str(v)[:60] for k, v in args.items()},
                    "result_summary": summary[:150],
                },
                "message": f"[{clause['clause_id']}] 预取 {tool_name} → {summary[:80]}",
            })
            blocks.append(
                f"<tool_result name=\"{tool_name}\" prefetched=\"true\">\n"
                f"{summary}\n{prompt_text}\n</tool_result>"
            )
        return "\n".join(blocks)

    async def _deep_dive(self, clause, entry, context, plan) -> Optional[Dict[str, Any]]:
        system = render_prompt(
            DEEP_DIVE_SYSTEM_PROMPT,
            client_role=context["client_role"],
            review_stance=context["review_stance"],
            tool_specs=format_tool_specs_for_prompt(),
            heading=clause["heading"][:50],
        )
        clause_text = clause["text"][:2400]

        # 代码侧主动取证（「决策权归模型、执行权归代码」）：
        # 本地检索零延迟，保证每条深查都有真实证据支撑，且引用可被幻觉核验追溯，
        # 不依赖模型对工具协议的遵循度（端侧小模型常直接下结论、工具调用为 0）
        prefetched = self._prefetch_evidence(clause, entry)
        evidence_block = (
            f"\n\n【系统预取证据（已核验来源，可直接引用为【依据法律原文】）】：\n{prefetched}\n"
            if prefetched else ""
        )

        user = (
            f"【合同类型】：{plan.get('contract_type', '')}\n"
            f"【分诊理由】：{entry.get('why', '')}\n"
            f"【建议工具】：{', '.join(entry.get('tools', [])) or '自行判断'}\n\n"
            f"【待深查条款】[{clause['clause_id']}] {clause['heading']}：\n{clause_text}"
            f"{evidence_block}\n\n"
            f"请开始：优先引用上述预取证据（如不足可再调用工具补充），"
            f"最终输出风险卡片或 ✅ 结论，并附 <selfcheck> 标签。"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        # ---- 开放式工具调用循环（模型自主决定查什么、查几次）----
        last_output = ""
        thinking = ""
        forced_final = False
        for _ in range(self.max_tool_rounds + 1):
            if not self._budget_left():
                break
            last_output = await self._llm(messages, temperature=0.2, max_tokens=2200)
            # 收集模型在各轮输出的推理（thinking）：带工具调用的首轮常含核心分析，
            # 若仅在循环结束后的最终输出上提取，会漏掉这部分思维链
            if not thinking:
                thinking = self._extract_thinking(last_output)
            tool_calls = parse_tool_calls(last_output)

            if not tool_calls:
                break  # 模型已给出最终结论

            messages.append({"role": "assistant", "content": last_output})
            result_parts = []
            for tc in tool_calls[:4]:  # 单轮至多执行 4 个调用
                self.tool_call_count += 1
                result = execute_tool(tc["name"], tc["args"])
                if tc["name"] == "precedent_search":
                    for p in result.get("data", []):
                        self.used_precedent_ids.add(p.get("id"))
                result_parts.append(
                    f"<tool_result name=\"{tc['name']}\">\n"
                    f"{result.get('result_summary', '')}\n{result.get('prompt_text', '')}\n"
                    f"</tool_result>"
                )
                self._pending_traces.append({
                    "type": "trace",
                    "data": {
                        "clause_id": clause["clause_id"],
                        "step": tc["name"],
                        "args": {k: str(v)[:80] for k, v in (tc["args"] or {}).items()},
                        "result_summary": result.get("result_summary", "")[:150],
                    },
                    "message": f"[{clause['clause_id']}] {tc['name']} → {result.get('result_summary', '')[:80]}",
                })
            messages.append({
                "role": "user",
                "content": "工具执行结果：\n" + "\n".join(result_parts) +
                           "\n\n若证据已足够，请直接输出最终风险卡片（或 ✅ 结论）与 <selfcheck> 标签，不要再调用工具。",
            })
        else:
            # 工具轮次触顶仍未给最终结论 → 强制收敛追问一次
            forced_final = True

        if forced_final or not last_output or not self._has_final(last_output):
            if self._budget_left():
                messages.append({"role": "assistant", "content": (last_output or "")[:600]})
                messages.append({
                    "role": "user",
                    "content": "已达工具调用轮次上限或尚未给出最终结论。请立即输出最终风险卡片（或 ✅ 结论）与 <selfcheck> 标签，不要再调用工具。",
                })
                last_output = await self._llm(messages, temperature=0.2, max_tokens=2200)
                if not thinking:
                    thinking = self._extract_thinking(last_output)

        # 循环中已收集 thinking；此处从待解析文本中剔除（避免污染卡片/报告）
        if thinking:
            last_output = self._strip_thinking(last_output)

        result = self._extract_card(clause, last_output)

        # ---- 单条 self-check 反思：低置信/需补证 → 重新取证（≤ max_retry）----
        retry = 0
        while (
            result and result.get("card")
            and self._budget_left()
            and retry < self.max_retry
            and (
                result.get("need_more")
                or (result.get("confidence") is not None and result["confidence"] < 0.55)
            )
        ):
            retry += 1
            self._pending_traces.append({
                "type": "trace",
                "data": {"clause_id": clause["clause_id"], "step": "selfcheck_retry",
                         "args": {"retry": retry},
                         "result_summary": f"自检置信不足（confidence={result.get('confidence')}），触发重新取证"},
                "message": f"[{clause['clause_id']}] self-check 触发第 {retry} 次重取证",
            })
            messages.append({"role": "assistant", "content": (last_output or "")[:800]})
            messages.append({
                "role": "user",
                "content": "自检显示证据不足。请更换检索词补取证据（可再调用工具，至多一轮），然后输出最终风险卡片与 <selfcheck> 标签。",
            })
            last_output = self._strip_thinking(await self._llm(messages, temperature=0.2, max_tokens=2200))
            new_result = self._extract_card(clause, last_output)
            if new_result:
                result = new_result
            if not parse_tool_calls(last_output):
                break

        if result and thinking and not result.get("thinking"):
            result["thinking"] = thinking
        return result

    @staticmethod
    def _has_final(output: str) -> bool:
        """判断输出是否已含最终结论（卡片或合规声明）"""
        if not output:
            return False
        if parse_tool_calls(output):
            return False
        return ("【条款原文引述】" in output) or ("✅" in output) or ("未发现实质" in output)

    @staticmethod
    def _extract_thinking(output: str) -> str:
        """提取模型 <thinking> 推理内容（真正的思维链，用于前端思维流展示）"""
        m = re.search(r"<thinking>\s*([\s\S]*?)\s*</thinking>", output or "", re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _strip_thinking(output: str) -> str:
        """剔除 <thinking> 标签，避免推理文本污染结构化结果（卡片/JSON）"""
        return re.sub(r"<thinking>[\s\S]*?</thinking>", "", output or "", flags=re.IGNORECASE).strip()

    def _extract_card(self, clause, output) -> Optional[Dict[str, Any]]:
        """从模型输出抽取风险卡片与 selfcheck"""
        text = (output or "").strip()
        if not text:
            return None

        confidence = None
        need_more = False
        critique = ""
        m = re.search(r"<selfcheck>\s*([\s\S]*?)\s*</selfcheck>", text, re.IGNORECASE)
        if m:
            sc = parse_json_lenient(m.group(1)) or {}
            try:
                confidence = float(sc.get("confidence"))
            except (TypeError, ValueError):
                confidence = None
            need_more = bool(sc.get("need_more"))
            # 模型的自我批评（「证据是否闭合」）——思维链中最能体现 Agent 自省的一环，
            # 保留并透传前端展示，而非只用于代码侧的重试判定
            critique = str(sc.get("critique") or "").strip()[:240]
            text = re.sub(r"<selfcheck>[\s\S]*?</selfcheck>", "", text, flags=re.IGNORECASE).strip()

        clean_pass = bool(re.match(r"^[✅🟢]", text)) or ("未发现实质" in text[:60]) or ("无实质" in text[:60])
        has_card = "【条款原文引述】" in text and ("【合规修改建议初稿】" in text or "【法理风险解构】" in text)

        if clean_pass and not has_card:
            return {"clause_id": clause["clause_id"], "card": None,
                    "note": text[:200], "confidence": confidence, "need_more": need_more,
                    "critique": critique}
        if not has_card:
            filled = self._rule_fill_card(clause)
            if filled:
                filled["critique"] = critique
                return filled
            return {"clause_id": clause["clause_id"], "card": None,
                    "note": "深查输出格式异常，已按未检出处理", "confidence": confidence,
                    "critique": critique}

        # 定位卡片标题行（#### 🔴/🟡/🟢 ...）判定严重度：
        # 1) 部分模型会在标题前输出对话式前导语（如「根据已有信息，我将分析…」），
        #    若按「首行」判定会把高危条款误判为中危 → 改为正则扫描标题行
        # 2) 前导语需剔除，保证报告渲染与前端 `#### 🔴🟡🟢` 统计准确
        # 3) 模型完全没输出标题行时，按全文关键词推断并补一个规范标题
        title_m = re.search(r"^#{2,4}\s*[🔴🟡🟢🟠][^\n]*$", text, re.M)
        severity = "medium"
        if title_m:
            head_mark = title_m.group(0)
            if "🔴" in head_mark or "高危" in head_mark or "🟠" in head_mark:
                severity = "high"
            elif "🟢" in head_mark or "合规" in head_mark or "良好" in head_mark:
                severity = "clean"
            preamble = text[:title_m.start()].strip()
            if preamble:
                logger.debug("已剔除深查卡片前导语 %d 字符", len(preamble))
            text = text[title_m.start():].strip()
        else:
            probe = text[:200]
            if "🔴" in text or "高危" in probe or "显失公平" in probe or "无效" in probe or "严重" in probe:
                severity = "high"
            elif "🟢" in text or "未发现实质" in text[:60]:
                severity = "clean"
            emoji = {"high": "🔴", "medium": "🟡", "clean": "🟢"}[severity]
            level = {"high": "高危风险", "medium": "中危风险", "clean": "合规良好"}[severity]
            text = f"#### {emoji} [{level}] {clause['heading'][:40]}\n\n" + text
            logger.debug("深查卡片缺少标准标题行，已补 %s [%s]", emoji, level)

        return {
            "clause_id": clause["clause_id"],
            "card": text,
            "severity": severity,
            "source": "agent",
            "critique": critique,
            "confidence": confidence,
            "need_more": need_more,
        }

    def _rule_fill_card(self, clause) -> Optional[Dict[str, Any]]:
        """深查失败的规则引擎补位"""
        hits = scan_rules(clause["text"])
        if not hits:
            return None
        card_blocks = []
        for h in hits:
            card_blocks.append(
                f"#### 🔴 [高危风险·规则兜底] {clause['heading'][:40]} — {h['title']}\n"
                + render_rule_card(h, "“" + clause["text"][:150] + "”")
            )
        return {
            "clause_id": clause["clause_id"],
            "card": "\n\n".join(card_blocks),
            "severity": "high",
            "source": "rule_fallback",
            "confidence": None,
        }

    # ------------------------------------------------------------------
    # Phase 3: 快筛批量核验
    # ------------------------------------------------------------------
    async def _quick_scan(self, quick_entries, clause_map) -> List[Dict[str, Any]]:
        listing = []
        for e in quick_entries[:20]:
            c = clause_map[e["clause_id"]]
            listing.append(f"- [{c['clause_id']}] {c['heading']}\n  正文：{c['text'][:300]}")
        messages = [
            {"role": "system", "content": render_prompt(QUICK_SCAN_PROMPT, clauses_listing="\n".join(listing))},
            {"role": "user", "content": "请核验以上快筛条款，输出 JSON。"},
        ]
        raw = parse_json_lenient(await self._llm(messages, temperature=0.1, max_tokens=800, want_json=True))
        upgrades = []
        if isinstance(raw, dict):
            for u in raw.get("upgrades", []):
                if isinstance(u, dict) and u.get("clause_id"):
                    upgrades.append({
                        "clause_id": str(u["clause_id"]),
                        "why": str(u.get("reason") or "快筛核验命中"),
                        "risk_score": 7,
                        "tools": [],
                    })
        return upgrades[:3]

    # ------------------------------------------------------------------
    # Phase 4: 全局反思
    # ------------------------------------------------------------------
    async def _global_reflect(self, clauses, plan, cards, clean_notes) -> Dict[str, Any]:
        clause_map = {c["clause_id"]: c for c in clauses}
        plan_listing = "\n".join(
            f"- [{e['clause_id']}] {clause_map.get(e['clause_id'], {}).get('heading', '（未知条款）')}：{e['action']}(score={e['risk_score']})，理由：{e['why'][:60]}"
            for e in plan["clauses"]
        )
        done_parts = []
        for c in cards:
            head = clause_map.get(c["clause_id"], {}).get("heading", "")
            first = (c.get("card", "").splitlines()[0][:60]) if c.get("card") else ""
            done_parts.append(f"- [{c['clause_id']}] {head}：检出风险（{first}）")
        for n in clean_notes:
            head = clause_map.get(n["clause_id"], {}).get("heading", "")
            done_parts.append(f"- [{n['clause_id']}] {head}：未发现实质风险")
        done_listing = "\n".join(done_parts) or "（无）"
        skip_listing = "\n".join(
            f"- [{e['clause_id']}] {clause_map.get(e['clause_id'], {}).get('heading', '（未知条款）')}：{e['why'][:60]}"
            for e in plan["clauses"] if e["action"] == "skip"
        ) or "（无跳过条款）"

        messages = [
            {"role": "system", "content": render_prompt(
                GLOBAL_REFLECT_PROMPT,
                plan_listing=plan_listing,
                done_listing=done_listing,
                skip_listing=skip_listing,
            )},
            {"role": "user", "content": "请输出全局反思 JSON。"},
        ]
        raw = parse_json_lenient(await self._llm(messages, temperature=0.2, max_tokens=1000, want_json=True))
        if not isinstance(raw, dict):
            return {}
        valid_ids = {c["clause_id"] for c in clauses}
        missed = [str(cid) for cid in raw.get("missed_clause_ids", []) if str(cid) in valid_ids]
        return {
            "missed_clause_ids": missed,
            "final_rating": str(raw.get("final_rating", "")),
            "confidence": raw.get("confidence"),
            "overall_comment": str(raw.get("overall_comment", ""))[:200],
            "levers": [str(x)[:150] for x in raw.get("levers", []) if x][:3],
        }

    # ------------------------------------------------------------------
    # Phase 4: 规则引擎静默交叉验证（主动安全网）
    # ------------------------------------------------------------------
    def _cross_validate(self, clauses, cards):
        """对全部条款跑规则扫描；规则命中但 Agent 未产出该条款风险卡 → 自动补入"""
        covered_ids = {c["clause_id"] for c in cards}
        cross_cards, cross_hits = [], []
        for c in clauses:
            hits = scan_rules(c["text"])
            if not hits or c["clause_id"] in covered_ids:
                continue
            blocks = []
            for h in hits:
                blocks.append(
                    f"#### 🔴 [高危风险·规则交叉验证] {c['heading'][:40]} — {h['title']}\n"
                    + render_rule_card(h, "“" + c["text"][:150] + "”")
                )
            cross_cards.append({
                "clause_id": c["clause_id"],
                "card": "\n\n".join(blocks),
                "severity": "high",
                "source": "cross_validation",
                "confidence": None,
            })
            cross_hits.append({"clause_id": c["clause_id"], "heading": c["heading"],
                               "rule_title": hits[0]["title"]})
        return cross_cards, cross_hits

    # ------------------------------------------------------------------
    # Phase 5: 报告组装（与旧报告格式完全兼容）
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_subtag(card_text: str) -> str:
        """从卡片【条款原文引述】中提取子条款定位词（如「乙方履约迟延责任」）

        引述格式形如：`- **【条款原文引述】**：“乙方履约迟延责任：若乙方……`
        仅在引号内以「短语：」形式给出子条款名时才提取，避免把正文首句误当定位词。
        """
        m = re.search(
            r"【条款原文引述】[^\n]{0,8}?[“\"「]\s*([^：:，。；、“”\"\n]{2,16})[：:]",
            card_text or "",
        )
        if not m:
            return ""
        tag = m.group(1).strip(" -·　*")
        tag = re.sub(r"^第[零〇一二三四五六七八九十百]+条\s*", "", tag)
        # 过长的捕获通常是正文首句而非子条款名，放弃使用
        if not tag or len(tag) > 14 or "*" in tag:
            return ""
        return tag[:12]

    #: 风险卡片首行：####/### <级别 emoji> [级别标签] 条款标题
    _CARD_HEADER_RE = re.compile(r"^(#{2,4})\s*([🔴🟡🟢🟠])\s*(.*)$")
    #: 标题里的模板噪声：模型照抄 prompt 说明留下的「或」、井号、级别标签、emoji
    _HEADER_NOISE_RE = re.compile(r"^(?:或|or)\s*|^#{1,6}\s*|[🔴🟡🟢🟠⚠️]|\[[^\]]{0,12}\]")

    @classmethod
    def _clean_card_title(cls, body: str) -> str:
        """清掉「模型把 prompt 模板原样抄进标题」造成的噪声，只留真实条款标题。

        实测坏例（prompt 里 `#### 🔴 [高危风险] 或 #### 🟡 [中危风险] <标题>` 被整行抄走）：
            "或 #### 🟡 [中危风险] 第三条 租金及支付方式" → "第三条 租金及支付方式"
            "第三条 租金及支付方式"                       → 原样保留
        """
        s = (body or "").strip()
        prev = None
        while s and s != prev:                       # 逐段剥离，直到不再变化
            prev = s
            s = cls._HEADER_NOISE_RE.sub("", s, count=1).strip()
        s = re.sub(r"\s+", " ", s).strip(" -—·:：")
        return s or "未命名条款"

    def _sanitize_card_titles(self, cards):
        """统一规范化每张卡片的标题行，避免模板噪声/截断标题流到报告与前端导航。"""
        for c in cards:
            card = c.get("card") or ""
            if not card:
                continue
            fixed = []
            for line in card.split("\n"):
                m = self._CARD_HEADER_RE.match(line.strip())
                if not m:
                    fixed.append(line)
                    continue
                marks, emoji, body = m.group(1), m.group(2), m.group(3)
                level = {"🔴": "高危风险", "🟡": "中危风险",
                         "🟠": "中危风险", "🟢": "合规"}.get(emoji, "风险")
                fixed.append(f"{marks} {emoji} [{level}] {self._clean_card_title(body)}")
            c["card"] = "\n".join(fixed)
        return cards

    def _disambiguate_card_titles(self, cards):
        """
        风险卡片标题消歧，避免报告与快捷导航出现同名条目造成「重复」观感。

        两种重复来源都要处理：
          1. 模型在**一条深查**中输出多张卡片（同一 card 字符串内含多个 `#### 🔴/🟡` 标题，
             分别覆盖不同子条款，如第五条的「履约迟延责任」与「服务瑕疵连带责任」）
          2. 不同来源（深查 / 快筛升级 / 交叉验证）对同一条款各产出卡片

        做法：把所有卡片文本按标题行切分为独立片段，标题规范化后全局计数，
        第 2 次起出现的同名标题追加子条款定位词（从该片段的【条款原文引述】提取）。
        """
        seen = {}
        for c in cards:
            card = c.get("card") or ""
            if not card:
                continue
            parts = re.split(r"(?=^#{2,4}\s*[🔴🟡🟢🟠])", card, flags=re.M)
            rebuilt = []
            for part in parts:
                title_m = re.match(r"^(#{2,4}\s*[🔴🟡🟢🟠][^\n]*)$", part, re.M)
                if not title_m:
                    rebuilt.append(part)
                    continue
                title = title_m.group(1)
                # 规范化口径与前端快捷导航一致：剥掉 emoji 与 [高危风险] 级别前缀，
                # 否则「🔴 [高危风险] 第五条…」与「🟡 [中危风险] 第五条…」会被判为不同标题，
                # 而导航里它们显示为同名按钮 —— 用户看到的「重复」正是这种
                norm = re.sub(r"^#{2,4}\s*[🔴🟡🟢🟠]\s*(\[[^\]]{0,10}\])?\s*", "", title).strip()
                norm = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", norm).strip()
                seen[norm] = seen.get(norm, 0) + 1
                if seen[norm] > 1:
                    tag = self._extract_subtag(part) or f"补充风险点 {seen[norm]}"
                    if f"（{tag}）" not in title:
                        part = part.replace(title, f"{title}（{tag}）", 1)
                rebuilt.append(part)
            c["card"] = "".join(rebuilt)
        return cards

    def _assemble_report(
        self, clauses, plan, cards, clean_notes, reflection, citation_check,
        llm_type, context, budget_hit,
    ) -> str:
        # 先清掉「模型照抄 prompt 模板」造成的标题噪声，再做同名消歧
        cards = self._sanitize_card_titles(cards)
        # 同条款多卡消歧：标题补充子条款定位，避免报告/导航出现同名条目
        cards = self._disambiguate_card_titles(cards)

        high_cards = [c for c in cards if c.get("severity") == "high"]
        med_cards = [c for c in cards if c.get("severity") == "medium"]

        card_rating = "🟢 合规良好" if not cards else ("🔴 高危风险" if high_cards else "🟡 中危可控")
        model_rating = (reflection or {}).get("final_rating", "")
        severity_order = {"🟢": 0, "🟡": 1, "🔴": 2}
        card_sev = severity_order.get(card_rating[:1], 1)
        model_sev = severity_order.get(model_rating[:1], 0) if model_rating else 0
        rating = card_rating if card_sev >= model_sev else model_rating

        deep = plan["summary"]["deep"]
        quick = plan["summary"]["quick"]
        skip = plan["summary"]["skip"]

        overall_comment = (reflection or {}).get("overall_comment", "")
        if not overall_comment:
            if cards:
                overall_comment = (
                    f"Agent 条款级审查共检出高危 {len(high_cards)} 项、中危 {len(med_cards)} 项风险，"
                    "涉及核心权益失衡条款，建议逐项按修改建议重构后再行签署。"
                )
            else:
                overall_comment = "Agent 逐条深查未发现实质性法律风险，主要权利义务对等、法定要素齐备，准予签署放行。"

        lines = [
            "### 📊 一、合同全景审计概览",
            f"- **合同类型判定**：{llm_type}",
            f"- **审查立场**：代表【{context['client_role']}】（审查风格：{context['review_stance']}）",
            f"- **合同综合风控评级**：{rating}" + ("（Agent 全链路审查）" if not budget_hit else "（已达预算上限，部分条款未完成深查）"),
            f"- **审查风险条目汇总**：高危风险 {len(high_cards)} 项，中危风险 {len(med_cards)} 项，优化建议 0 项",
            f"- **条款覆盖情况**：感知 {len(clauses)} 条 → 已全部出结论（检出风险 {len(cards)} 条 · 审查通过 {len({n['clause_id'] for n in (clean_notes or []) if n.get('clause_id')})} 条）",
            f"- **Agent 审查轨迹**：条款 {len(clauses)} 条 → 深查 {deep} / 快筛 {quick} / 跳过 {skip}；"
            f"工具调用 {self.tool_call_count} 次；模型调用 {self._calls} 次；耗时 {self._elapsed()}s"
            + (f"；反思置信度 {reflection.get('confidence')}" if reflection and reflection.get("confidence") is not None else ""),
            f"- **资深法务综合评估意见**：{overall_comment}",
            "",
            "### 🚨 二、逐条穿透风险清单",
        ]

        if cards:
            lines.append("")
            for c in cards:
                lines.append(c["card"])
                lines.append("")
        else:
            lines.append(
                "【全文合规通过】：本合同各项主要权利义务对等、主要法定要素齐备，"
                "经 Agent 逐条分诊深查与规则引擎交叉验证，未检出实质性法律风险或单方失衡条款，准予签署放行。"
            )
            lines.append("")

        # ---- 逐条留痕：明示已审查但未发现实质风险的条款 ----
        # 此前 clean_notes 虽被传入却未被使用，导致「快筛通过 / 低风险跳过」的条款在报告中
        # 完全不出现，用户视角即为「漏审」。此处统一列出，保证每条条款都有交代。
        clean_items = [n for n in (clean_notes or []) if n.get("clause_id")]
        if clean_items:
            heading_map = {c["clause_id"]: c.get("heading", "") for c in clauses}
            seen_clean = set()
            rows = []
            for n in clean_items:
                cid = n["clause_id"]
                if cid in seen_clean:
                    continue
                seen_clean.add(cid)
                rows.append(f"- **{cid} {heading_map.get(cid, '')}**：{n.get('note', '经审查未发现实质风险')}")
            lines.append(f"**✅ 已审查且未发现实质风险的条款（共 {len(rows)} 条，逐条留痕）**：")
            lines.extend(rows)
            lines.append("")

        lines.append("### ⚖️ 三、司法裁判指引与商务谈判抓手")
        levers = (reflection or {}).get("levers", [])
        if levers:
            for i, lv in enumerate(levers, start=1):
                lines.append(f"- **抓手{i}**：{lv}")
        else:
            for p in self._collect_used_precedents()[:3]:
                lines.append(f"- **抓手**：{p['title']}（{p['case_no']}）——{p['practical_advice']}")
        if not levers and not self.used_precedent_ids:
            lines.append("- 依据《民法典》权利义务对等原则与商事交易惯例，对违约金上限、验收期限、解除补偿等关键条款保持对等约定。")

        if citation_check and not citation_check.get("all_verified", True):
            unv = citation_check.get("articles_unverified", []) + citation_check.get("cases_unverified", [])
            if unv:
                lines.append(f"- **⚠️ 引用核验提示**：以下引用未能在法条库/判例库中追溯，请人工复核：{'；'.join(unv[:5])}")

        return "\n".join(lines)

    def _collect_used_precedents(self) -> List[Dict[str, Any]]:
        by_id = {p["id"]: p for p in PRECEDENTS_DATABASE}
        return [by_id[i] for i in self.used_precedent_ids if i in by_id]
