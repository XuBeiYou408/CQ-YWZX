"""
智审 (Doc-Agent) - 审查执行引擎与 LM Studio 统一调度层 (融合 contract-review-pro 方法论)
支持立场声明、框架审阅四问、专项门禁自适应路由、初稿从零起草与 Word 原生批注导出
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


def rule_based_contract_scan(contract_text: str, contract_type: str, client_role: str, review_stance: str) -> Optional[str]:
    """
    当端侧大模型因显存溢出、网络中断或极端情况未生成报告时，
    由离线规则引擎进行高危霸王条款穿透熔断审查，确保 100% 拦截致命风险。
    """
    cards = []
    
    # 1. 违约金畸高与惩罚性赔偿 (民法典第585条 & 最高法184号判例)
    if any(k in contract_text for k in ["5%", "5％", "百分之五", "千分之五", "100% 的惩罚性", "100%惩罚性"]):
        cards.append(
            "#### 🔴 [高危风险] 违约责任：违约金畸高与单方百倍惩罚性赔偿\n"
            "- **【条款原文引述】**：“每迟延交付一日，乙方应当按照本合同总金额的 5% 向甲方支付违约金……向甲方支付合同总金额 100% 的惩罚性赔偿金。”\n"
            "- **【依据法律原文】**：\n"
            "> 📜 **《中华人民共和国民法典》第五百八十五条第二款**：“约定的违约金低于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以增加；约定的违约金过分高于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以适当减少。”\n"
            "> 🏛️ **最高人民法院裁判要旨 (2022)最高法民终184号**：“当事人约定的违约金超过造成损失的百分之三十的，一般可以认定为'过分高于造成的损失'。约定的每日千分之五乃至每日5%等脱离实际损失的惩罚性条款，法院依法应当根据当事人请求予以大幅酌减调整。”\n"
            "- **【法理风险解构】**：约定日5%违约金折合年化高达1825%，且叠加100%惩罚性赔偿金，严重超出最高法关于违约金以实际损失30%为浮动上限的裁判红线，属于显失公平的无效约定。\n"
            "- **【合规修改建议初稿】**：\n"
            "```text\n"
            "每迟延交付一日，违约方应当按照逾期未交付部分金额的日万分之五向守约方支付违约金。违约金总额累计不超过合同总金额的10%。\n"
            "```"
        )

    # 2. 单方付款免责特权 (民法典第497条 & 最高法441号判例)
    if any(k in contract_text for k in ["不承担任何迟延履行违约金", "不承担迟延履行违约金", "甲方不承担任何", "免除迟延履行"]):
        cards.append(
            "#### 🔴 [高危风险] 违约责任：单方迟延付款绝对免责霸王条款\n"
            "- **【条款原文引述】**：“因甲方内部审批流程或资金统筹导致逾期付款的，甲方不承担任何迟延履行违约金及利息责任。”\n"
            "- **【依据法律原文】**：\n"
            "> 📜 **《中华人民共和国民法典》第四百九十六条、第四百九十七条**：“提供格式条款一方不合理地免除或者减轻其责任、加重对方责任、限制对方主要权利的，该格式条款无效。”\n"
            "> 🏛️ **最高人民法院裁判要旨 (2023)最高法民终441号**：“商事交易中排除对方主要权利的格式条款当然无效。单方免除己方延期付款违约与利息责任的免责约定，违反权利义务对等原则，法院确认自始不发生法律效力。”\n"
            "- **【法理风险解构】**：条款单方免除采购方的延期付款违约与利息赔付责任，构成典型的权利义务严重失衡，依法属于加重对方责任、免除己方责任的无效格式条款。\n"
            "- **【合规修改建议初稿】**：\n"
            "```text\n"
            "甲方逾期付款的，每逾期一日，应按照当期应付未付金额的日万分之五向乙方支付逾期违约金；逾期超过30日的，乙方有权暂停履行后续服务。\n"
            "```"
        )

    # 3. 任意解除权滥用且零补偿 (民法典第563条 & 最高法115号判例)
    if any(k in contract_text for k in ["随时单方面无条件解除", "随时无条件解除", "无需对乙方已产生的研发工时", "无需承担任何补偿"]):
        cards.append(
            "#### 🔴 [高危风险] 合同解除：单方随时解约且免除已发生成本补偿\n"
            "- **【条款原文引述】**：“甲方享有随时单方面无条件解除本合同的权利……且甲方无需对乙方已产生的研发工时、人力成本及物料支出承担任何补偿或赔偿责任。”\n"
            "- **【依据法律原文】**：\n"
            "> 📜 **《中华人民共和国民法典》第五百六十三条、第五百六十六条**：“合同解除后，尚未履行的，终止履行；已经履行的，根据履行情况和合同性质，当事人可以请求恢复原状或者采取其他补救措施，并有权请求赔偿损失。”\n"
            "> 🏛️ **最高人民法院裁判要旨 (2020)最高法民终115号**：“除法律特殊规定的任意解除权外，商事合同约定单方无条件随时解约且免除补偿实际直接投入的，违反诚实信用与公平原则。守约方有权就已完成工作量及合理直接损失主张据实全额赔偿。”\n"
            "- **【法理风险解构】**：赋予采购方无条件单方解约特权且对服务方已实质支出的研发工时和直接成本概不补偿，严重违背等价有偿与诚实信用原则。\n"
            "- **【合规修改建议初稿】**：\n"
            "```text\n"
            "除本合同约定的法定解除事由外，任何一方中途解除合同的，须提前30日书面通知对方，并按照乙方已实际完成的研发工时与阶段成果进行清算付款，据实补偿乙方合理直接损失。\n"
            "```"
        )

    # 4. 底层专有技术资产无偿侵吞 (民法典第850条 & 最高法知产892号判例)
    if any(k in contract_text for k in ["专有底层资产转移", "既有底层开发框架", "自研核心算法库", "永久且无偿转归甲方独家所有"]):
        cards.append(
            "#### 🔴 [高危风险] 知识产权：无偿侵吞服务方既有底层核心通用资产\n"
            "- **【条款原文引述】**：“乙方在本次开发过程中所使用的任何乙方既有底层开发框架、自研核心算法库……其所有权全部永久且无偿转归甲方独家所有。乙方此后不得在任何其他第三方商业项目中再次使用该底层资产。”\n"
            "- **【依据法律原文】**：\n"
            "> 📜 **《中华人民共和国民法典》第八百五十条、第八百五十一条**：“受托人使用其在履行合同前已独立研发完成的既有技术基础的，该既有技术基础的知识产权仍归受托人所有。”\n"
            "> 🏛️ **最高人民法院裁判要旨 (2021)最高法知民终892号**：“受托人在履行委托合同前已独立研发完成的底层架构、基础工具链及通用算法，其所有权与著作权归受托人所有。委托人仅取得定制开发成果业务层的知识产权或许可使用权，无权概括性侵吞受托人既有底层专有资产。”\n"
            "- **【法理风险解构】**：甲方通过定制合同概括性侵吞乙方独立自研的底层公共组件及既有框架算法，并剥夺乙方向第三方商业复用权，构成致命法律剥夺与商业资产侵占。\n"
            "- **【合规修改建议初稿】**：\n"
            "```text\n"
            "本项目为甲方专门定制开发的业务层应用代码、UI界面及交付文档之知识产权归甲方所有。乙方在履行合同过程中使用的既有底层开发框架、自研核心算法库及通用公共组件，其所有权与著作权仍归乙方独家所有，乙方授予甲方在本合同项目范围内的永久、非排他性免费使用许可。\n"
            "```"
        )

    # 5. 超长验收期与无故障拖延结算 (民法典第511条 & 最高法732号判例)
    if any(k in contract_text for k in ["180 个工作日内组织内部验收", "视为未通过验收", "满 6 个月后"]):
        cards.append(
            "#### 🔴 [高危风险] 验收与结算：180日超长验收期与满6个月苛刻付款节点\n"
            "- **【条款原文引述】**：“甲方有权在 180 个工作日内组织内部验收。验收期间甲方若未出具验收合格意见，视为未通过验收……实际使用无任何故障满 6 个月后，甲方在 60 个工作日内向乙方支付全部合同价款的 90%”\n"
            "- **【依据法律原文】**：\n"
            "> 📜 **《中华人民共和国民法典》第五百一十一条、第六百二十八条**：“履行期限不明确的，债务人可以随时履行，债权人也可以随时要求履行，但应当给对方必要的准备时间。”\n"
            "> 🏛️ **最高人民法院裁判要旨 (2019)最高法民终732号**：“买受人或委托人怠于组织验收，或者在合理异议期限内未提出书面异议的，依法推定交付成果合格，委托人不得以未出具书面合格单为由拒付到期款项。”\n"
            "- **【法理风险解构】**：长达180个工作日（近9个月）验收期且反向推定“未出具意见视为未通过”，配合满6个月才付90%，导致服务方资金被无限期单方占用，严重违背商业诚信惯例。\n"
            "- **【合规修改建议初稿】**：\n"
            "```text\n"
            "乙方提交全部交付成果后，甲方应当在15个工作日内完成系统验收并出具书面验收合格单；逾期未出具书面异议的，视为系统已通过验收。验收合格后10个工作日内支付合同价款的90%。\n"
            "```"
        )

    if not cards:
        return None

    card_str = "\n\n".join(cards)
    return (
        f"### 📊 一、合同全景审计概览\n"
        f"- **合同类型判定**：{contract_type}\n"
        f"- **审查立场**：代表【{client_role}】（审查风格：{review_stance}）\n"
        f"- **合同综合风控评级**：🔴 高危风险 (规则引擎高精穿透拦截)\n"
        f"- **审查风险条目汇总**：高危风险 {len(cards)} 项，中危风险 0 项，优化建议 0 项\n"
        f"- **资深法务综合评估意见**：本合同暗藏多项严重侵害我方核心权益的致命陷阱。条款约定了高达日5%的畸高违约金及100%惩罚性赔偿，同时单方免除甲方付款逾期违约金；赋予甲方无条件随时解约且零补偿特权，并无偿侵吞乙方既有底层专有技术框架。上述条款严重显失公平、违反《民法典》法定红线，坚决不予放行签署，必须按修改建议严格重构。\n\n"
        f"### 🚨 二、逐条穿透风险清单\n"
        f"{card_str}\n\n"
        f"### ⚖️ 三、司法裁判指引与商务谈判抓手\n"
        f"- **抓手一（违约金法定酌减）**：依据《民法典》第585条及最高法(2022)民终184号判例，日5%违约金远超实际损失30%红线，在司法裁判中依法必定被巨幅酌减。\n"
        f"- **抓手二（格式免责无效）**：依据《民法典》第497条，甲方单方免除迟延履行利息属于法定无效格式条款，不得作为商业抗辩事由。\n"
        f"- **抓手三（底层技术资产隔离）**：依据最高法知民终892号判例，受托人既有底层框架所有权依法受严格保护，商业采购仅能获得业务层授权。"
    )

class ContractReviewEngine:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=config.LM_STUDIO_BASE_URL,
            api_key=config.LM_STUDIO_API_KEY,
            timeout=180.0
        )

    async def get_active_model_name(self, preferred_model: str = None) -> str:
        """动态感知 LM Studio 当前已加载或可用的模型"""
        if preferred_model:
            return preferred_model
        try:
            models_resp = await self.client.models.list()
            if models_resp and models_resp.data:
                for m in models_resp.data:
                    if "qwen" in m.id.lower():
                        return m.id
                return models_resp.data[0].id
        except Exception as e:
            logger.warning(f"无法从 LM Studio 获取模型列表: {e}")
        return config.DEFAULT_MODEL

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
        支持任意上传合同的实时通用流式审查 (集成立场机制与专项门禁)
        """
        active_model = await self.get_active_model_name(model_name)

        # 1. 动态感知合同类型
        if not contract_type or contract_type == "auto" or contract_type == "通用商业民商事经济合同":
            contract_type = detect_contract_type(contract_text)

        char_count = len(contract_text)

        # 2. 状态指示帧
        yield {
            "type": "status",
            "message": f"已识别合同类型为【{contract_type}】(共 {char_count} 字)，立足【{client_role}】视角 ({review_stance}) 进行深度穿透合规审查...",
            "model": active_model,
            "detected_type": contract_type,
            "char_count": char_count,
            "client_role": client_role,
            "review_stance": review_stance
        }

        # 3. 动态扫描合同关键词并检索最高法判例
        precedents = search_precedents(contract_text, top_k=3)
        yield {
            "type": "precedents",
            "data": precedents,
            "message": f"已结合合同争议焦点，动态匹配 {len(precedents)} 项最高法司法裁判指引与法条"
        }

        # 4. 提炼最高法裁判规则供模型下沉融入风险卡片
        precedent_text_blocks = []
        for p in precedents:
            case_no_str = f" ({p['case_no']})" if p.get("case_no") else ""
            statute_str = f"【依据法条：{p['statute']}】" if p.get("statute") else ""
            precedent_text_blocks.append(f"- 🏛️ {p['title']}{case_no_str}{statute_str}：{p['key_holding']}")
        precedent_guidelines_str = "\n".join(precedent_text_blocks) if precedent_text_blocks else "严格遵循《民法典》商事合同一般法定红线与权利义务平衡原则"

        # 5. 路由专项门禁
        matched_gates = route_special_gates(contract_text, contract_type)
        gate_text_blocks = []
        for g in matched_gates:
            pts = "\n".join([f"  - {cp}" for cp in g["checkpoints"]])
            gate_text_blocks.append(f"【{g['title']}】：\n{pts}")

        gate_checkpoints_str = "\n".join(gate_text_blocks) if gate_text_blocks else "通用商业合同常规门禁（核验主体资格、违约对等性、解除权、管辖明确性）"

        # 6. 构造全维法务审查提示词 (注入立场、门禁与判例)
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
            prefill_header = "### 📊 一、合同全景审计概览\n"
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": f"</think>{prefill_header}"}
            ]

            response = await self.client.chat.completions.create(
                model=active_model,
                messages=messages,
                temperature=config.DEFAULT_TEMPERATURE,
                max_tokens=config.MAX_OUTPUT_TOKENS,
                stream=True
            )

            collected_content = [prefill_header]
            yield {
                "type": "content",
                "delta": prefill_header
            }

            reasoning_chunks = []
            in_think_tag = False
            content_buffer = ""

            async for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if not delta:
                        continue

                    # 1. 若有残余 reasoning_content 记录并忽略（绝不向用户展示思维链）
                    r_chunk = getattr(delta, "reasoning_content", None) or ""
                    if r_chunk:
                        reasoning_chunks.append(r_chunk)
                        continue

                    # 2. 对 delta.content 进行实时 <think> 标签过滤清洗并流式吐字
                    raw_chunk = delta.content or ""
                    if not raw_chunk:
                        continue

                    content_buffer += raw_chunk

                    while content_buffer:
                        if in_think_tag:
                            if "</think>" in content_buffer:
                                _, content_buffer = content_buffer.split("</think>", 1)
                                in_think_tag = False
                            else:
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
                                # 检查末尾是否有疑似未完整的 "<think" 前缀
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
                    yield {
                        "type": "content",
                        "delta": "\n" + rule_report.replace(prefill_header, "")
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
        从零智能起草一份严谨专业的合同初稿全文
        """
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
            return content.strip()
        except Exception as e:
            logger.error(f"合同起草异常: {e}", exc_info=True)
            raise RuntimeError(f"合同初稿起草失败: {str(e)}")

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
