"""
智审 (Doc-Agent) - 审查执行引擎与 LM Studio 统一调度层 (融合 contract-review-pro 方法论)
v2.0 Agent 化改造（融合终版计划书）：
  - stream_review 签名与全部旧 SSE 事件保持不变（向后兼容）
  - 大合同（条款 ≥ 8 且字数 ≥ 2000）→ 走 Agent 主循环（感知→规划→行动→反思）
  - 小合同 / Agent 失效 → 降级为旧管道全量单次审查（下限不降低）
  - rule_based_contract_scan 保留为兜底工具 + 规则交叉验证安全网
"""
import re
import os
import logging
from typing import AsyncGenerator, Dict, Any, List, Optional
from openai import AsyncOpenAI

from config import config
from contract.prompts import (
    AUDIT_SYSTEM_PROMPT,
    CONTRACT_REVISE_FULL_PROMPT,
    CONTRACT_DRAFT_FROM_SCRATCH_PROMPT
)
from contract.precedents import search_precedents
from contract.parser import detect_contract_type
from contract.gates.special_gates import route_special_gates
from contract.document_annotator import annotator
from contract.rule_cards import rule_engine_fallback_report
from contract.agent import ContractReviewAgent, LLMClient

logger = logging.getLogger(__name__)


def rule_based_contract_scan(contract_text: str, contract_type: str, client_role: str, review_stance: str) -> Optional[str]:
    """
    当端侧大模型因显存溢出、网络中断或极端情况未生成报告时，
    由离线规则引擎进行高危霸王条款穿透熔断审查，确保 100% 拦截致命风险。
    （v2.0：规则卡片数据已抽离至 rule_cards.py，本函数输出格式与旧版完全一致）
    """
    return rule_engine_fallback_report(contract_text, contract_type, client_role, review_stance)


class ContractReviewEngine:
    def __init__(self):
        # 默认客户端（本地 LM Studio）。真正的连接参数由模型管理配置决定，
        # 每次进入审查入口时通过 _ensure_client() 按需重建（见 model_config.py）。
        self.client = AsyncOpenAI(
            base_url=config.LM_STUDIO_BASE_URL,
            api_key=config.LM_STUDIO_API_KEY,
            timeout=180.0
        )
        self._client_key = (config.LM_STUDIO_BASE_URL, config.LM_STUDIO_API_KEY)

    def _ensure_client(self) -> AsyncOpenAI:
        """
        按「模型管理」里的当前生效配置准备 OpenAI 客户端。

        · 本地模式 → 指向 LM Studio（用户可在面板里改端口/地址）
        · 云端模式 → 指向所选云端服务（DeepSeek / Kimi / 通义 / 智谱 / 自定义）
        仅当 (base_url, api_key) 发生变化时才重建实例，避免每次审查重复建连。
        """
        try:
            from contract import model_config
            eff = model_config.get_effective()
        except Exception as e:
            logger.debug(f"读取模型配置失败（沿用当前客户端）: {e}")
            return self.client

        new_key = (eff["base_url"], eff["api_key"])
        if new_key != self._client_key:
            self.client = AsyncOpenAI(base_url=eff["base_url"], api_key=eff["api_key"], timeout=180.0)
            self._client_key = new_key
            logger.info(
                f"模型客户端已切换: provider={eff['provider']} base_url={eff['base_url']} "
                f"model={eff['model']}（密钥{'已配置' if eff['api_key'] and not eff['api_key'].startswith('sk-missing') else '缺失'}）"
            )
        return self.client

    async def _list_loaded_models(self) -> List[str]:
        """
        查询 LM Studio 当前「已加载」的模型列表（/api/v0/models 为 LM Studio 专有接口）。
        用于避免选中未加载模型而触发漫长的即时加载（27B 等大模型加载可能耗时数分钟）。
        """
        base = (config.LM_STUDIO_BASE_URL or "").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{base}/api/v0/models")
                if r.status_code == 200:
                    return [m.get("id", "") for m in (r.json().get("data") or [])
                            if m.get("state") == "loaded" and m.get("id")]
        except Exception as e:
            logger.debug(f"查询 LM Studio 已加载模型失败（忽略，回退通用列表）: {e}")
        return []

    async def get_active_model_name(self, preferred_model: str = None) -> str:
        """
        动态感知当前生效的审查模型（模型管理面板 > 环境变量 > 自动优选）。

        优选顺序：
          1. 显式指定（调用方入参，如前端单次请求指定）
          2. 环境变量 AGENT_MODEL（管理员级硬锁定，默认留空即不生效）
          3. **模型管理面板里用户配置的模型**（云端模式必取其云端模型；
             本地模式取面板里选定的本地模型）
          4. 本地模式且面板未指定模型时，回退原有的自动优选：
             跟随 WorkBuddy 会话本地模型 → 已加载且非 reasoning 的 qwen → 已加载任意模型
             → 模型列表中的 qwen → 列表第一个 → DEFAULT_MODEL
        """
        self._ensure_client()

        if preferred_model:
            return preferred_model
        if config.AGENT_MODEL:
            return config.AGENT_MODEL

        # —— 模型管理面板的配置（用户显式选择，优先级仅低于环境变量硬锁定）——
        try:
            from contract import model_config
            cfg = model_config.load()
            eff = model_config.get_effective()
            if not eff.get("is_local"):
                # 云端模式：直接使用云端模型，不走任何本地 LM Studio 优选逻辑
                picked = (eff.get("model") or "").strip() or "deepseek-chat"
                logger.info(f"按模型管理配置使用云端模型: {picked}（{eff.get('base_url')}）")
                return picked
            pinned_local = (cfg.get("local", {}).get("model") or "").strip()
            if pinned_local:
                logger.info(f"按模型管理配置使用本地模型: {pinned_local}")
                return pinned_local
            logger.info("模型管理未指定本地模型，回退自动优选（跟随会话 / 已加载模型）")
        except Exception as e:
            logger.debug(f"读取模型管理配置失败（回退自动优选）: {e}")

        def _pick(cands: List[str], strict_non_reasoning: bool = True) -> str:
            """从候选里挑优：先排除 reasoning 类；再优先 instruct 类"""
            reason_marks = ("reasoning", "distill", "think")
            if strict_non_reasoning:
                non_reason = [m for m in cands
                              if not any(k in m.lower() for k in reason_marks)]
                pool = non_reason or cands
            else:
                pool = cands
            instruct = [m for m in pool if "instruct" in m.lower()]
            return (instruct or pool)[0] if (instruct or pool) else ""

        # 1) 已加载模型优先（避免触发即时加载）
        loaded = await self._list_loaded_models()
        if loaded:
            # 1.0 跟随「用户当前会话正在使用的本地模型」：该模型此刻必然已加载
            #     （用户正在与它对话），复用它既贴合用户预期，又避免 LM Studio
            #     换模型（卸载+重载大模型可带来分钟级时延）。
            #     会话用的是云端模型 / 读不到 → 不干预，继续走下面的既有优选逻辑。
            try:
                from contract.session_model import model_id_matches, read_session_local_model

                hint = read_session_local_model()
                if hint:
                    for m in loaded:
                        if model_id_matches(m, hint):
                            logger.info(f"选用会话正在使用的本地模型: {m}（已加载: {loaded}）")
                            return m
                    logger.info(f"会话本地模型 {hint} 当前未加载，改按已加载模型优选（避免触发加载）")
            except Exception as e:
                logger.debug(f"会话本地模型提示不可用（忽略）: {e}")

            qwen_loaded = [m for m in loaded if "qwen" in m.lower()]
            if qwen_loaded:
                picked = _pick(qwen_loaded)
                if picked:
                    logger.info(f"选用已加载模型: {picked}（已加载: {loaded}）")
                    return picked
            picked = _pick(loaded, strict_non_reasoning=False)
            if picked:
                logger.info(f"选用已加载模型: {picked}（已加载: {loaded}）")
                return picked

        # 2) 回退：通用模型列表
        try:
            models_resp = await self.client.models.list()
            if models_resp and models_resp.data:
                qwen_all = [m.id for m in models_resp.data if "qwen" in m.id.lower()]
                if qwen_all:
                    picked = _pick(qwen_all)
                    if picked:
                        logger.info(f"选用模型（未预加载）: {picked}")
                        return picked
                return models_resp.data[0].id
        except Exception as e:
            logger.warning(f"无法从 LM Studio 获取模型列表: {e}")
        return config.DEFAULT_MODEL

    # ==================================================================
    # 主入口：签名与旧版完全一致（向后兼容）
    # ==================================================================
    async def stream_review(
        self,
        contract_text: str,
        contract_type: str = None,
        client_role: str = "中立合规把关",
        review_stance: str = "对等平衡",
        focus_dimensions: List[str] = None,
        model_name: str = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        v2.0：Agent 主循环（ReAct）+ 旧管道降级兜底
        """
        active_model = await self.get_active_model_name(model_name)

        # 1. 动态感知合同类型（轨道 1：关键词预判）
        if not contract_type or contract_type == "auto" or contract_type == "通用商业民商事经济合同":
            contract_type = detect_contract_type(contract_text)

        char_count = len(contract_text)

        # 2. 状态指示帧（保留旧行为）
        yield {
            "type": "status",
            "message": f"已识别合同类型为【{contract_type}】(共 {char_count} 字)，立足【{client_role}】视角 ({review_stance}) 进行深度穿透合规审查...",
            "model": active_model,
            "detected_type": contract_type,
            "char_count": char_count,
            "client_role": client_role,
            "review_stance": review_stance
        }

        # 3. 路由决策：去除门槛要求，所有合同全量走 Agent 闭环（感知→规划→行动→反思 + 全程思维链透传）
        use_agent = config.AGENT_ENABLED

        if use_agent:
            agent_report = None
            agent_meta: Dict[str, Any] = {}
            agent_failed = False
            try:
                llm = LLMClient(self.client, active_model)
                agent = ContractReviewAgent(llm)
                async for frame in agent.run(
                    contract_text=contract_text,
                    contract_type_hint=contract_type,
                    client_role=client_role,
                    review_stance=review_stance,
                    focus_dimensions=focus_dimensions,
                ):
                    ftype = frame.get("type")
                    if ftype == "agent_report":
                        agent_report = frame.get("data")
                        agent_meta = frame.get("meta") or {}
                        continue  # 内部事件不透传
                    if ftype == "agent_fallback_mode":
                        # 拆条彻底失败 → 全文模式（旧管道保命）
                        yield {
                            "type": "fallback_notice",
                            "data": {"scope": "engine", "reason": frame.get("reason")},
                            "message": frame.get("message", "Agent 拆条失败，已降级为全量单次审查模式"),
                        }
                        agent_failed = True
                        break
                    yield frame
            except Exception as e:
                logger.error(f"Agent 主循环异常，降级旧管道: {e}", exc_info=True)
                agent_failed = True

            if agent_failed or agent_report is None:
                yield {
                    "type": "fallback_notice",
                    "data": {"scope": "engine", "reason": "agent_failed"},
                    "message": "Agent 流程未产出报告，已自动降级为全量单次审查模式",
                }
                async for frame in self._legacy_single_shot_review(
                    contract_text, contract_type, client_role, review_stance, focus_dimensions, active_model
                ):
                    yield frame
                return

            # Agent 统计元信息透传（前端轨迹面板展示工具/模型调用与耗时）
            yield {"type": "agent_meta", "data": agent_meta}

            # Agent 报告收尾：content / precedents / draft / done（与旧管道收尾一致）
            async for frame in self._emit_report_tail(
                agent_report, contract_text, contract_type, client_role, review_stance,
                agent_meta.get("used_precedents") or [],
            ):
                yield frame
            return

        # 4. 旧管道（小合同 / Agent 关闭）
        async for frame in self._legacy_single_shot_review(
            contract_text, contract_type, client_role, review_stance, focus_dimensions, active_model
        ):
            yield frame

    # ==================================================================
    # Agent 报告收尾（content 分段流式 + precedents + draft + done）
    # ==================================================================
    async def _emit_report_tail(
        self,
        report: str,
        contract_text: str,
        contract_type: str,
        client_role: str,
        review_stance: str,
        used_precedents: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # 1. 分段流式下发报告正文（保持前端打字机体验）
        chunk_size = 700
        for i in range(0, len(report), chunk_size):
            yield {"type": "content", "delta": report[i:i + chunk_size]}

        # 2. Agent 实际取证的判例透传（供前端司法参考面板）
        if used_precedents:
            yield {
                "type": "precedents",
                "data": used_precedents,
                "message": f"Agent 深查过程中共调取 {len(used_precedents)} 项司法裁判指引与法条",
            }

        # 3. 兜底防护：报告过短或异常时规则引擎穿透拦截（绝不谎报合规）
        if len(report) < 150:
            rule_report = rule_based_contract_scan(contract_text, contract_type, client_role, review_stance)
            if rule_report:
                yield {"type": "content", "delta": "\n" + rule_report}
            else:
                yield {
                    "type": "content",
                    "delta": "\n### ⚠️ 审查中断提示\n端侧大模型服务未返回完整内容，请检查本地 LM Studio 运行状态后点击重试。",
                }

        # 4. 合规初稿重构 + 完成事件（与旧管道逻辑一致）
        auto_draft = synthesize_revised_contract(contract_text, report)
        is_perfect = (
            ("合规良好" in report or "高危风险 0 项" in report or "高危 0" in report)
            and ("未检出" in report or "无法律风险" in report or "准予签署" in report or "合规通过" in report)
            and not any(x in report for x in ["#### 🔴", "#### 🟡", "高危风险 1", "高危风险 2", "高危风险 3", "高危风险 4", "高危风险 5", "高危风险 6", "高危风险 7"])
        )

        yield {
            "type": "draft",
            "data": auto_draft or contract_text,
            "is_perfect": is_perfect,
            "message": "原合同合规度极高，全文准予放行！" if is_perfect else "合规修改初稿已完成智能原位重构！"
        }

        yield {
            "type": "done",
            "message": "Agent 全链路合同风险穿透审查已完成！",
        }

    # ==================================================================
    # 旧管道：全量单次审查（小合同豁免 / Agent 降级保命路径）
    # ==================================================================
    async def _legacy_single_shot_review(
        self,
        contract_text: str,
        contract_type: str,
        client_role: str,
        review_stance: str,
        focus_dimensions: List[str],
        active_model: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """v1.0 固定管道原逻辑（关键词检索判例 → 门禁路由 → 单 Prompt 出报告 → 规则兜底）"""
        # 1. 动态扫描合同关键词并检索最高法判例
        precedents = search_precedents(contract_text, top_k=3)
        yield {
            "type": "precedents",
            "data": precedents,
            "message": f"已结合合同争议焦点，动态匹配 {len(precedents)} 项最高法司法裁判指引与法条"
        }

        # 2. 提炼最高法裁判规则供模型下沉融入风险卡片
        precedent_text_blocks = []
        for p in precedents:
            case_no_str = f" ({p['case_no']})" if p.get("case_no") else ""
            statute_str = f"【依据法条：{p['statute']}】" if p.get("statute") else ""
            precedent_text_blocks.append(f"- 🏛️ {p['title']}{case_no_str}{statute_str}：{p['key_holding']}")
        precedent_guidelines_str = "\n".join(precedent_text_blocks) if precedent_text_blocks else "严格遵循《民法典》商事合同一般法定红线与权利义务平衡原则"

        # 3. 路由专项门禁
        matched_gates = route_special_gates(contract_text, contract_type)
        gate_text_blocks = []
        for g in matched_gates:
            pts = "\n".join([f"  - {cp}" for cp in g["checkpoints"]])
            gate_text_blocks.append(f"【{g['title']}】：\n{pts}")

        gate_checkpoints_str = "\n".join(gate_text_blocks) if gate_text_blocks else "通用商业合同常规门禁（核验主体资格、违约对等性、解除权、管辖明确性）"

        # 4. 构造全维法务审查提示词 (注入立场、门禁与判例)
        sys_prompt = AUDIT_SYSTEM_PROMPT.format(
            contract_type=contract_type,
            client_role=client_role,
            review_stance=review_stance,
            gate_checkpoints=gate_checkpoints_str,
            precedent_guidelines=precedent_guidelines_str
        )
        user_prompt = (
            f"待审查合同类型：【{contract_type}】\n"
            f"我方代表立场：【{client_role}】（审查风格：{review_stance}）\n\n"
            f"待审查合同正文全文：\n{contract_text}"
        )

        try:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ]

            response = await self.client.chat.completions.create(
                model=active_model,
                messages=messages,
                temperature=config.DEFAULT_TEMPERATURE,
                max_tokens=config.MAX_OUTPUT_TOKENS,
                stream=True
            )

            collected_content = []
            in_think_tag = False
            content_buffer = ""

            async for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if not delta:
                        continue

                    # 1. 若有 reasoning_content，实时透传为 thinking 帧，确保思维链始终向用户展示
                    r_chunk = getattr(delta, "reasoning_content", None) or ""
                    if r_chunk:
                        yield {
                            "type": "thinking",
                            "data": {
                                "phase": "review",
                                "clause_id": "",
                                "text": r_chunk,
                            },
                            "message": "审查分析思考中...",
                        }
                        continue

                    # 2. 对 delta.content 进行实时 <think> 标签流式分离：
                    #    <think> 内内容作为 thinking 帧透传，正文作为 content 帧透传
                    raw_chunk = delta.content or ""
                    if not raw_chunk:
                        continue

                    content_buffer += raw_chunk

                    while content_buffer:
                        if in_think_tag:
                            if "</think>" in content_buffer:
                                think_part, content_buffer = content_buffer.split("</think>", 1)
                                in_think_tag = False
                                if think_part:
                                    yield {
                                        "type": "thinking",
                                        "data": {"phase": "review", "clause_id": "", "text": think_part},
                                        "message": "审查分析思考中...",
                                    }
                            else:
                                partial_end = False
                                for i in range(1, 8):
                                    if content_buffer.endswith("</think>"[:i]):
                                        partial_end = True
                                        break
                                if partial_end and len(content_buffer) <= 10:
                                    break
                                yield {
                                    "type": "thinking",
                                    "data": {"phase": "review", "clause_id": "", "text": content_buffer},
                                    "message": "审查分析思考中...",
                                }
                                content_buffer = ""
                                break
                        else:
                            if "<think>" in content_buffer:
                                clean_part, content_buffer = content_buffer.split("<think>", 1)
                                in_think_tag = True
                                if clean_part:
                                    collected_content.append(clean_part)
                                    yield {
                                        "type": "content",
                                        "delta": clean_part
                                    }
                            else:
                                partial_match = False
                                for i in range(1, 7):
                                    if content_buffer.endswith("<think"[:i]):
                                        partial_match = True
                                        break
                                if partial_match and len(content_buffer) <= 10:
                                    break

                                collected_content.append(content_buffer)
                                yield {
                                    "type": "content",
                                    "delta": content_buffer
                                }
                                content_buffer = ""

            # 3. 循环结束后强制 FLUSH 残余缓冲区内容
            if content_buffer and not in_think_tag:
                clean_tail = content_buffer.replace("</think>", "").replace("<think>", "").strip()
                if clean_tail:
                    collected_content.append(clean_tail)
                    yield {
                        "type": "content",
                        "delta": clean_tail
                    }
                content_buffer = ""

            full_report = "".join(collected_content).strip()

            # 4. 兜底防护：若模型输出过短或异常，启用规则引擎穿透拦截，绝不谎报合规
            if len(full_report) < 150:
                rule_report = rule_based_contract_scan(contract_text, contract_type, client_role, review_stance)
                if rule_report:
                    full_report = rule_report
                    # 修复：原代码此处引用了未定义的 prefill_header（规则兜底报告里并无该前缀），
                    # 一旦走到"模型输出过短 → 规则引擎兜底"这条路径就会 NameError 崩溃。
                    # 规则报告本身已自带标题，直接整段下发即可。
                    yield {
                        "type": "content",
                        "delta": "\n" + rule_report
                    }
                else:
                    err_hint = "\n### ⚠️ 审查中断提示\n端侧大模型服务未返回完整内容，请检查本地 LM Studio 运行状态后点击重试。"
                    full_report += err_hint
                    yield {
                        "type": "content",
                        "delta": err_hint
                    }

            # 5. 基于审查报告自动生成合规初稿全文 (带绿标保护)
            auto_draft = synthesize_revised_contract(contract_text, full_report)
            is_perfect = (
                ("合规良好" in full_report or "高危风险 0 项" in full_report or "高危 0" in full_report)
                and ("未检出" in full_report or "无法律风险" in full_report or "准予签署" in full_report or "合规通过" in full_report)
                and not any(x in full_report for x in ["#### 🔴", "#### 🟡", "高危风险 1", "高危风险 2", "高危风险 3", "高危风险 4", "高危风险 5", "高危风险 6", "高危风险 7"])
            )

            yield {
                "type": "draft",
                "data": auto_draft or contract_text,
                "is_perfect": is_perfect,
                "message": "原合同合规度极高，全文准予放行！" if is_perfect else "合规修改初稿已完成智能原位重构！"
            }

            yield {
                "type": "done",
                "message": "合同全维度法律风险穿透审查已完成！"
            }

        except Exception as e:
            logger.error(f"LM Studio 推理异常: {str(e)}", exc_info=True)
            yield {
                "type": "error",
                "message": f"审查推理异常: {str(e)}。请检查本地模型服务是否正常运行。"
            }

    async def generate_revised_draft(
        self,
        original_text: str,
        review_report: str,
        model_name: str = None
    ) -> str:
        """生成合规修改后的合同初稿全文"""
        # 1. 绿标保护：如果本身审查合格或没有修改建议，直接原样返回原合同
        if "合规良好" in review_report and ("未检出" in review_report or "高危风险 0 项" in review_report):
            return original_text

        synthesized = synthesize_revised_contract(original_text, review_report)
        if "【修改说明" in synthesized:
            logger.info("已完成条款高精原位重构，直接交付合规初稿")
            return synthesized

        # 若规则未覆盖，则请求端侧模型辅助
        try:
            active_model = await self.get_active_model_name(model_name)
            prompt = (
                f"原合同文本：\n{original_text}\n\n"
                f"法务审查报告与修改意见：\n{review_report}\n\n"
                "请直接输出修改后的正式合同全文（合规初稿），绝对不要输出任何思考过程或前置说明："
            )
            response = await self.client.chat.completions.create(
                model=active_model,
                messages=[
                    {"role": "system", "content": CONTRACT_REVISE_FULL_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=3000
            )
            msg = response.choices[0].message
            content = (msg.content or "").strip()
            if content and not content.startswith("我们需要") and len(content) > 100:
                return content
        except Exception as e:
            logger.warning(f"模型重构初稿异常: {e}")

        return synthesized or original_text

    async def generate_new_draft(
        self,
        contract_type: str,
        party_a: str,
        party_b: str,
        core_subject: str,
        payment_terms: str = "按阶段验收付款",
        special_terms: str = "",
        client_role: str = "甲方",
        model_name: str = None
    ) -> str:
        """
        依据民法典标准示范文本库快速合成高标准商事合同初稿全文。
        优先使用权威示范范本快速合成（毫秒级响应、严格符合民法典规范、立场自适应），
        若匹配不到模板或需要深度AI自由扩展，则平滑回退至本地大模型生成。
        """
        from contract.draft_templates import render_contract_draft

        try:
            # 1. 优先使用权威示范范本快速合成（毫秒级极速生成，零幻觉）
            draft = render_contract_draft(
                contract_type=contract_type,
                party_a=party_a,
                party_b=party_b,
                core_subject=core_subject,
                payment_terms=payment_terms,
                special_terms=special_terms,
                client_role=client_role
            )
            if draft and len(draft) >= 500:
                logger.info(f"已依据【{contract_type}】示范范本库快速合成初稿 (共 {len(draft)} 字)")
                return draft
        except Exception as e:
            logger.warning(f"示范范本快速合成异常，回退至大模型从零生成: {e}")

        # 2. 回退模式：若示范文本未命中，调用大模型生成
        active_model = await self.get_active_model_name(model_name)
        sys_prompt = CONTRACT_DRAFT_FROM_SCRATCH_PROMPT.format(client_role=client_role)

        user_prompt = (
            f"【合同起草任务委托】：\n"
            f"- 合同类型：{contract_type}\n"
            f"- 甲方主体名称：{party_a}\n"
            f"- 乙方主体名称：{party_b}\n"
            f"- 合作核心标的与金额：{core_subject}\n"
            f"- 价款结算与付款节点：{payment_terms}\n"
            f"- 补充商业特约：{special_terms or '双方按照民法典通用商业惯例承担对等违约与保密责任'}\n"
            f"- 委托方代表立场：{client_role}\n\n"
            f"请根据上述商业要素，严格遵循《中华人民共和国民法典》规范，直接起草输出完整、规范、权责平衡的正式合同初稿全文："
        )

        try:
            response = await self.client.chat.completions.create(
                model=active_model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                max_tokens=3500
            )
            content = response.choices[0].message.content or ""
            clean_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            return clean_content or content.strip()
        except Exception as e:
            logger.error(f"合同起草异常: {e}", exc_info=True)
            raise RuntimeError(f"合同初稿起草失败: {str(e)}")

    async def review_full(
        self,
        contract_text: str,
        contract_type: str = None,
        client_role: str = "中立合规把关",
        review_stance: str = "对等平衡",
        model_name: str = None,
    ) -> Dict[str, Any]:
        """
        非流式完整审查（供 MCP Tool 调用）。
        纯包装：内部复用 stream_review()，收集全部帧后返回结构化结果。
        不改动任何现有审查逻辑。
        返回: {
            "report": str,          # 完整审查报告 Markdown
            "draft": str,           # 合规修改初稿
            "is_perfect": bool,     # 是否合规良好无需修改
            "contract_type": str,   # 识别出的合同类型
            "char_count": int,      # 合同字数
        }
        """
        report_parts: List[str] = []
        draft_text = ""
        is_perfect = False
        detected_type = contract_type or ""
        char_count = 0

        async for frame in self.stream_review(
            contract_text=contract_text,
            contract_type=contract_type,
            client_role=client_role,
            review_stance=review_stance,
            model_name=model_name,
        ):
            ftype = frame.get("type")
            if ftype == "status":
                detected_type = frame.get("detected_type", detected_type)
                char_count = frame.get("char_count", char_count)
            elif ftype == "content":
                report_parts.append(frame.get("delta", ""))
            elif ftype == "draft":
                draft_text = frame.get("data", "") or draft_text
                is_perfect = bool(frame.get("is_perfect", False))

        return {
            "report": "".join(report_parts).strip(),
            "draft": draft_text,
            "is_perfect": is_perfect,
            "contract_type": detected_type,
            "char_count": char_count,
        }

    def export_annotated_docx(self, original_text: str, review_report: str, title: str, output_path: str) -> str:
        """调用 DocumentAnnotator 导出带原生批注与修订的 Word 文档"""
        return annotator.generate_annotated_docx(original_text, review_report, title, output_path)


def synthesize_revised_contract(original_text: str, review_report: str) -> str:
    """
    基于审查报告中提取出的【条款原文引述】与【合规修改建议初稿】，
    智能原位替换原合同中的高危/中危条款，迅速生成完整且准确的合规初稿全文。
    """
    if not original_text:
        return ""
    if not review_report:
        return original_text

    # 绿标保护：若报告显示无任何高危或中危，原样返回原合同全文
    if "合规良好" in review_report and ("未检出" in review_report or "高危风险 0 项" in review_report):
        return original_text

    revised = original_text
    cards = re.split(r'####\s*[🔴🟡🟢]?', review_report)

    for card in cards[1:]:
        orig_m = re.search(r'【条款原文引述】[\s\S]*?[“"\'「]([\s\S]*?)[”"\'」]', card)
        sugg_m = re.search(r'【合规修改建议初稿】[\s\S]*?```(?:text)?\s*([\s\S]*?)\s*```', card)

        if not orig_m or not sugg_m:
            continue

        orig_clause = orig_m.group(1).strip()
        new_clause = sugg_m.group(1).strip()

        if not orig_clause or not new_clause:
            continue

        # 1. 直接全文精确替换
        if orig_clause in revised:
            replacement = f"{new_clause} 【修改说明：已依据《民法典》及合规要求修正】"
            revised = revised.replace(orig_clause, replacement, 1)
            continue

        # 2. 忽略换行/标点差异，按主干句子在原合同中定位
        sentences = [s.strip() for s in re.split(r'[\r\n；。]+', orig_clause) if len(s.strip()) >= 8]
        for sent in sentences:
            if sent in revised:
                replacement = f"{new_clause} 【修改说明：已依据《民法典》及合规要求修正】"
                revised = revised.replace(sent, replacement, 1)
                break

    return revised


engine = ContractReviewEngine()
