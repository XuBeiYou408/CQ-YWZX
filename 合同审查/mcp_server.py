"""
智审 (Doc-Agent) - WorkBuddy MCP Server（双轨 Tool 轨）
========================================================
轨道 B 入口：将合同审查能力暴露为 WorkBuddy 可调用的 MCP 工具。

双轨设计（见 合同改造计划书/）：
- 轻量工具（5 个）：条款风险扫描 / 法条检索 / 判例检索 / 类型识别 / 改写建议
  —— 同步、无 LLM、秒级返回，与 8020 Web 工作台（Agent 轨）零冲突
- 完整工具（4 个）：合同审查 / 文件审查+批注版导出 / 批注版导出 / 新合同起草
  —— 走共享核心引擎 ContractReviewEngine（LM Studio），分钟级

启动性能（吸取 kb-tool 优化教训）：
- 模块级仅 import FastMCP + 只读核心检索层（pymupdf/docx 轻量链），
  数秒内完成 stdio 握手，避免 WorkBuddy 新会话首问工具快照踩空；
- 重型 engine 链（openai/agent 全链）在完整审查工具首次调用时才懒加载。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from mcp.server.fastmcp import FastMCP

from contract.mcp_tools import (
    scan_clause_risk as _scan_clause_risk,
    lookup_statute as _lookup_statute,
    search_precedent as _search_precedent,
    identify_contract_type as _identify_contract_type,
    get_clause_rewrite as _get_clause_rewrite,
)

mcp = FastMCP(
    "contract-reviewer",
    instructions=(
        "企业合同合规审查工具集（双轨）。\n"
        "轻量轨（秒级）：条款风险扫描、法条检索、判例检索、合同类型识别、条款改写建议"
        "——适合业务员日常快速答疑，不依赖 LM Studio。\n"
        "完整轨（分钟级，需本地 LM Studio 运行）：合同全文审查、合同文件审查并导出"
        "Word 红线批注版、批注版导出、新合同起草——适合需要正式审查报告的场景。\n"
        "凡用户提到合同审查/合同风险/法条/判例/起草合同，应从本工具集选择对应工具，"
        "不要用网络搜索回答法律审查问题。"
    ),
)


# ==================================================================
# 轻量轨（5 个，同步，秒级，无 LLM）
# ==================================================================

@mcp.tool()
def scan_clause_risk(clause_text: str) -> str:
    """扫描单条合同条款的高危风险（规则引擎，秒级）。

    适用：用户贴出**单条条款**问"这条有什么风险/有没有问题"。
    例如"甲方有权随时解除合同且不承担任何违约责任"这类霸王条款必被命中。
    不适用：整份合同的交叉审查（请改用 review_contract / review_contract_file）。
    """
    return _scan_clause_risk(clause_text)


@mcp.tool()
def lookup_statute(keyword: str, top_k: int = 3) -> str:
    """检索内置法条库（民法典合同编 + 最高法合同编通则解释），返回法条原文。

    适用：用户问"XX 怎么规定的/法律依据是什么"，如"违约金过高怎么规定"
    "格式条款无效情形有哪些"。
    """
    return _lookup_statute(keyword, top_k)


@mcp.tool()
def search_precedent(query: str, top_k: int = 3) -> str:
    """检索最高人民法院裁判指引判例库，返回案号+裁判要旨+实务建议。

    适用：用户问"有没有类似判例/这种条款法院怎么判"，如"违约金酌减的判例"。
    """
    return _search_precedent(query, top_k)


@mcp.tool()
def detect_contract_type(contract_text: str) -> str:
    """识别合同文本所属类型（买卖/租赁/劳动/技术开发/股权转让/借款等）。

    适用：上传合同后先识别类型；或为 get_clause_rewrite 提供类型参数。
    """
    return _identify_contract_type(contract_text)


@mcp.tool()
def get_clause_rewrite(clause_text: str, contract_type: str = "") -> str:
    """给出条款的合规改写建议：规则引擎修改建议 + 标准条款示范模板 + 必备要素清单。

    适用：用户问"这条怎么改更合规/给我一个标准版本"。
    contract_type 可选（可先调 detect_contract_type），可精确匹配该类型模板。
    """
    return _get_clause_rewrite(clause_text, contract_type)


# ==================================================================
# 完整轨（4 个，异步，走共享引擎 + LM Studio，分钟级）
# ==================================================================

@mcp.tool()
async def review_contract(
    contract_text: str,
    stance: str = "中立合规把关",
    review_style: str = "对等平衡",
) -> str:
    """完整审查合同文本（全维度法律审查 + 风险分级 + 修改建议 + 合规初稿）。

    适用：用户粘贴**合同全文（或较长片段）**要求完整审查，如"帮我审查这份合同"。
    不适用：单条条款快查（用 scan_clause_risk 更快）。
    参数：stance 审查立场（甲方/乙方/中立合规把关）；review_style 审查风格
    （对等平衡/强势防守/商业促成）。需要本地 LM Studio 运行，耗时分钟级。
    """
    from contract.engine import engine
    try:
        result = await engine.review_full(
            contract_text, client_role=stance, review_stance=review_style
        )
    except Exception as e:
        return (
            f"❌ 完整审查执行失败：{e}\n"
            "请确认 LM Studio 已在 127.0.0.1:1234 启动并加载了模型；"
            "或先使用轻量工具（scan_clause_risk / lookup_statute）进行快速风险扫描。"
        )

    sections = [
        f"## 📋 合同完整审查报告",
        f"- 合同类型：{result['contract_type'] or '未识别'}（共 {result['char_count']} 字）",
        f"- 审查立场：{stance}（风格：{review_style}）",
        "",
        result["report"] or "（无报告内容）",
    ]
    if result["draft"] and not result["is_perfect"]:
        sections += ["", "---", "## ✍️ 合规修改初稿（依据审查建议原位重构）", "", result["draft"]]
    elif result["is_perfect"]:
        sections += ["", "🎉 审查结论：合规良好，未发现需修改的高危/中危风险。"]
    return "\n".join(sections)


@mcp.tool()
async def review_contract_file(
    file_path: str,
    stance: str = "中立合规把关",
    review_style: str = "对等平衡",
) -> str:
    """审查合同文件（.docx/.pdf/.txt/.md），自动在原文件同目录生成 Word 红线批注版。

    适用：用户给出合同文件路径（或拖入文件）要求"帮我审查/改好"。
    产出：① 完整审查报告；② 原生批注+修订痕迹的 .docx（原文件同目录，
    文件名追加"_批注版"）；③ 审查报告 .md。需要本地 LM Studio，耗时分钟级。
    返回值仅为**结果摘要 + 交付文件路径**（不含报告全文，以节省上下文）；
    审查报告全文已写入 .md 文件，用户需要细节时再用 Read 工具读取该文件。
    """
    from contract.parser import parse_uploaded_file
    from contract.engine import engine

    file_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.isfile(file_path):
        return f"❌ 文件不存在：{file_path}"

    try:
        with open(file_path, "rb") as f:
            content_bytes = f.read()
        parsed = parse_uploaded_file(os.path.basename(file_path), content_bytes)
    except Exception as e:
        return f"❌ 文件解析失败：{e}（支持 .docx / .pdf / .txt / .md）"

    contract_text = (parsed.get("text") or "").strip() if isinstance(parsed, dict) else str(parsed)
    if not contract_text:
        return "❌ 未能从文件中提取到合同文本（可能是扫描件/图片型 PDF）。"

    try:
        result = await engine.review_full(
            contract_text, client_role=stance, review_stance=review_style
        )
    except Exception as e:
        return (
            f"❌ 完整审查执行失败：{e}\n请确认 LM Studio 已在 127.0.0.1:1234 启动并加载模型。"
        )

    # 产出文件：与原文件同目录
    out_dir = os.path.dirname(file_path)
    stem = os.path.splitext(os.path.basename(file_path))[0]
    docx_path = os.path.join(out_dir, f"{stem}_批注版.docx")
    report_md_path = os.path.join(out_dir, f"{stem}_审查报告.md")

    lines = [f"## 📋 合同完整审查报告", f"- 源文件：{file_path}",
             f"- 合同类型：{result['contract_type'] or '未识别'}（共 {result['char_count']} 字）",
             f"- 审查立场：{stance}（风格：{review_style}）", "",
             result["report"] or "（无报告内容）"]
    if result["draft"] and not result["is_perfect"]:
        lines += ["", "---", "## ✍️ 合规修改初稿", "", result["draft"]]
    report_md = "\n".join(lines)
    if result["is_perfect"]:
        report_md += "\n\n🎉 审查结论：合规良好，未发现需修改的高危/中危风险。"

    # 写审查报告 .md（始终生成，便于留存）
    try:
        with open(report_md_path, "w", encoding="utf-8") as f:
            f.write(report_md)
    except Exception:
        report_md_path = ""

    # 生成批注版 Word（合规良好且无 draft 时也导出绿标放行版）
    if result["is_perfect"]:
        docx_path = ""  # 无风险时跳过批注版生成
    else:
        try:
            if os.path.exists(docx_path):
                import time as _t
                docx_path = os.path.join(out_dir, f"{stem}_批注版_{_t.strftime('%H%M%S')}.docx")
            engine.export_annotated_docx(
                contract_text, result["report"], f"{stem} · 审阅批注版", docx_path
            )
        except Exception as e:
            docx_path = ""
            lines.append(f"\n> ⚠️ 批注版 Word 生成失败：{e}")

    summary = [
        f"审查完成：识别为【{result['contract_type'] or '未识别'}】（{result['char_count']} 字），"
        f"立场：{stance}（风格：{review_style}）。",
    ]
    # 从报告中提取风险计数（轻量正则，避免把全文塞进上下文）
    report_text = result["report"] or ""
    n_high = report_text.count("高危")
    n_mid = report_text.count("中危")
    if result["is_perfect"]:
        summary.append("🎉 审查结论：合规良好，未发现需修改的高危/中危风险。")
    else:
        summary.append(
            f"⚠️ 风险概况：文中提及高危 {n_high} 处、中危 {n_mid} 处"
            "（以报告全文为准）。"
        )
    if docx_path:
        summary.append(f"📄 批注版 Word：{docx_path}")
    elif result["is_perfect"]:
        summary.append("（合规良好，未生成批注版）")
    if report_md_path:
        summary.append(f"📝 审查报告全文（.md）：{report_md_path}")

    # 仅返回报告开头摘要预览（不返回全文），控制工具返回体积，
    # 防止大报告撑爆本地模型上下文导致收尾回答被 max_tokens 截断。
    preview = report_text[:600].rstrip()
    summary += [
        "",
        "报告开头预览：",
        preview + ("……" if len(report_text) > 600 else ""),
        "",
        "（以上仅为摘要。请直接向用户转达上述结论与文件路径；"
        "不要尝试复述报告全文。用户需要某项细节时，用 Read 工具读取 .md 报告文件的对应部分。）",
    ]
    return "\n".join(summary)


@mcp.tool()
async def export_annotated_docx(
    original_text: str,
    review_report: str,
    title: str = "合同审查审阅批注版",
    output_path: str = "",
) -> str:
    """将审查结果导出为带 Word 原生批注（Comments）与修订痕迹（Track Changes）的 .docx。

    适用：用户已获得审查报告（如上一步 review_contract 的结果），要求
    "导出 Word 批注版"。不适用：从文件开始审查（用 review_contract_file 一步到位）。
    output_path 为空时保存到原文本同目录不可知，默认保存到桌面。
    """
    from contract.engine import engine

    original_text = (original_text or "").strip()
    review_report = (review_report or "").strip()
    if not original_text or not review_report:
        return "❌ 需要同时提供 original_text（合同原文）与 review_report（审查报告）。"

    if not output_path:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        output_path = os.path.join(desktop, f"{title or '合同审查'}.docx")
    output_path = os.path.abspath(os.path.expanduser(output_path))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        result_path = engine.export_annotated_docx(original_text, review_report, title, output_path)
        return f"✅ 批注版 Word 已生成：{result_path}"
    except Exception as e:
        return f"❌ 批注版导出失败：{e}"


@mcp.tool()
async def draft_new_contract(
    contract_type: str,
    party_a: str,
    party_b: str,
    core_subject: str,
    payment_terms: str = "按阶段验收付款",
    special_terms: str = "",
    stance: str = "甲方",
) -> str:
    """从零智能起草一份新合同初稿全文（需本地 LM Studio）。

    适用：用户说"帮我起草一份XX合同"，并提供甲乙方名称与合作核心标的。
    参数：contract_type 合同类型（如 采购合同/技术开发合同/租赁合同）；
    party_a/party_b 甲乙方名称；core_subject 核心标的与金额；
    payment_terms 付款方式；special_terms 补充特约；stance 己方立场。
    """
    from contract.engine import engine
    try:
        draft = await engine.generate_new_draft(
            contract_type=contract_type,
            party_a=party_a,
            party_b=party_b,
            core_subject=core_subject,
            payment_terms=payment_terms,
            special_terms=special_terms,
            client_role=stance,
        )
    except Exception as e:
        return f"❌ 合同起草失败：{e}\n请确认 LM Studio 已在 127.0.0.1:1234 启动并加载模型。"

    header = (
        f"## 📜 合同起草初稿\n"
        f"- 类型：{contract_type}｜甲方：{party_a}｜乙方：{party_b}\n"
        f"- 立场：{stance}｜核心标的：{core_subject}\n\n---\n\n"
    )
    return header + (draft or "（起草结果为空）")


# ==================================================================
# 诊断工具（模型侧体检：不同机器的 LM Studio 环境差异排查入口）
# ==================================================================

@mcp.tool()
def ping() -> str:
    """体检本工具集的运行环境：LM Studio 是否在线、有哪些模型可用、各轨是否就绪。

    适用：完整审查/起草报错时先调用本工具定位问题（多数是 LM Studio 未启动、
    端口非默认 1234、或没有已加载模型）。
    """
    import json as _json
    import urllib.request

    from config import config as _cfg

    lines = ["== contract-reviewer 环境体检 =="]
    # 轻量轨：模块级已加载即就绪
    lines.append("轻量轨（5 个秒级工具）：✅ 就绪（不依赖 LM Studio）")

    base = _cfg.LM_STUDIO_BASE_URL.rstrip("/")
    if base.endswith("/v1"):
        probe_url = base[: -len("/v1")] + "/v1/models"
    else:
        probe_url = base + "/v1/models"
    lines.append(f"LM Studio 地址：{base}")
    # 模型管理（model_config.json）优先：报告真正生效的审查模型
    try:
        from contract import model_config as _mc

        _eff = _mc.get_effective()
        _cfgfile = _mc.load()
        lines.append(
            f"模型管理：provider={_eff['provider']}"
            f"（{'本地 LM Studio' if _eff['is_local'] else '云端 API'}）"
        )
        lines.append(f"  ▸ 生效地址：{_eff['base_url']}")
        lines.append(f"  ▸ 生效模型：{_eff['model']}")
        if not _eff["is_local"]:
            lines.append(f"  ▸ 云端密钥：{'已配置' if _eff['api_key'] and not _eff['api_key'].startswith('sk-missing') else '缺失（请在界面上填写）'}")
        elif _cfgfile.get("local", {}).get("model"):
            lines.append("  ▸ 说明：面板已指定本地模型，审查将固定使用它（不再跟随会话）")
        else:
            lines.append("  ▸ 说明：面板未指定本地模型，审查走自动优选（跟随会话 / 已加载模型）")
    except Exception as _e:
        lines.append(f"模型管理：读取失败（{_e}），回退配置默认值")

    lines.append(f"兜底默认模型（DEFAULT_MODEL）：{_cfg.DEFAULT_MODEL}")
    if _cfg.AGENT_MODEL:
        lines.append(f"硬锁定模型（AGENT_MODEL）：{_cfg.AGENT_MODEL}（优先级高于模型管理面板）")

    # 会话本地模型提示：当前会话用的本地模型若已加载，审查会优先复用它（避免换模型带来的时延）
    try:
        from contract.session_model import read_session_local_model

        _hint = read_session_local_model()
        if _hint:
            lines.append(f"会话本地模型：{_hint}（已加载则审查优先复用）")
    except Exception:
        pass

    try:
        req = urllib.request.Request(
            probe_url, headers={"Authorization": f"Bearer {_cfg.LM_STUDIO_API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _json.loads(r.read())
        ids = [m.get("id", "?") for m in data.get("data", [])]
        lines.append(f"LM Studio：✅ 在线，共 {len(ids)} 个可用模型")
        if ids:
            lines.append("可用模型：" + "、".join(ids[:10]) + ("…" if len(ids) > 10 else ""))
        lines.append("完整轨（审查/批注/起草）：✅ 可用（引擎会自动选择模型）")
    except Exception as e:
        lines.append("LM Studio：❌ 不可达（连接失败或超时）")
        lines.append(f"  原因：{e}")
        lines.append("  影响：轻量轨/风险扫描/法条判例检索不受影响；完整审查、")
        lines.append("        批注版导出、新合同起草将失败。")
        lines.append("  处理：① 启动 LM Studio 并加载任意 instruct 模型；")
        lines.append("        ② 若端口不是 1234，设置环境变量 LM_STUDIO_BASE_URL")
        lines.append("           （如 http://127.0.0.1:8080/v1）后重启本服务。")
    return "\n".join(lines)


if __name__ == "__main__":
    # 握手先行：轻量核心层在模块级已加载（约 1~2 秒），此处直接启动 stdio 服务；
    # 重型 engine 链在完整轨工具首次调用时懒加载，不阻塞协议握手。
    mcp.run(transport="stdio")
