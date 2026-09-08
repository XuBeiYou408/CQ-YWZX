import utils.noise_suppressor # noqa: F401 — 必须在所有其他导入之前执行
import os
import json
import time
import asyncio
from openai import OpenAI
from config import LOCAL_DB_PATH
from rag.retriever import zhaohui_and_rerank

# 初始化大模型裁判客户端（复用 DeepSeek API 评估生成质量）
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_API_URL")
)

# ==================== 优化版 rag_stream_generate ====================
def rag_stream_generate(query, combined_context):
    """
    优化点：与生产环境 system prompt 保持一致，不做额外修改。
    流式生成保持不变（评估需要精确测量 TTFT）。
    """
    system_prompt = (
        "你是一个毫无感情的、极其严谨的企业知识库检索机器人。\n"
        "【严格死律】：请【仅仅且只能】基于用户给定的【本地检索上下文】中明确提及的事实来回答问题。\n"
        "1. 如果上下文中没有提到能解答问题的相关核心信息，请不要做任何延伸扩展，直接回答：'抱歉，本地知识库中未查到相关核心信息。'\n"
        "2. 严禁动用你原本的预训练通用技术知识去凭空丰富、美化或者脑补答案。上下文里没有的内容，一律视为不存在。"
    )
    user_prompt = f"""请仔细阅读以下从本地知识库检索出来的关联文档片段，并回答用户的技术问题。
【本地检索上下文】：
\"\"\"
{combined_context}
\"\"\"

【用户问题】：{query}
请给出专业、逻辑清晰、针对性强的技术解答："""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
            stream=True
        )

        for chunk in response:
            delta_content = chunk.choices[0].delta.content
            if delta_content:
                yield delta_content
    except Exception as e:
        print(f"\n⚠️ 真实大模型流式生成异常: {e}")
        yield f"【系统错误：真实大模型流式生成失败 - {str(e)}】"

# ==================== 优化版 llm_judge_metrics ====================
def llm_judge_metrics(query, context, answer, ground_truth):
    """
    优化点：
    1. temperature=0.0 保证阅卷标准完全一致（可复现）
    2. 增加 3 级 few-shot 示例（高/中/低），覆盖完整评分区间，消除两极分化
    3. 增加 completeness（答案完整性）维度：对比 ground_truth，答案覆盖了几个要点
    4. 要求输出简短理由（reason），便于回溯分析每个 case 的评分逻辑
    5. API 失败时返回 None（不再静默填 0），由上层排除异常数据

    面试话术：采用经过校准的 LLM-as-Judge 方法，通过三级 few-shot 锚定评分标尺，
    从忠实度、相关性、完整性三个维度量化评估生成质量。
    """
    prompt = f"""你是一个极其严格的 RAG 问答系统全栈评估专家。请对以下内容进行客观打分。

【评分标尺示例（三级 Few-Shot 校准）】：

示例 1 — 高分案例（0.90+ 区域）：
  问题: "什么是向量数据库？"
  上下文: "向量数据库是专门用于存储和检索高维向量数据的数据库系统，通过向量相似度计算实现快速检索。"
  回答: "向量数据库是专门用于存储和检索高维向量数据的数据库系统，通过向量相似度计算实现快速检索。"
  参考答案: "向量数据库是一种专门用于存储和检索高维向量数据的数据库系统，通过向量索引算法实现高效的近似最近邻搜索。"
  评分: {{"faithfulness": 0.95, "answer_relevance": 0.95, "completeness": 0.70, "reason": "回答完全基于上下文无幻觉，直接回应了问题，但相比参考答案缺少'索引算法'和'近似最近邻'等细节"}}

示例 2 — 中分案例（0.50~0.70 区域，这是 RAG 系统最常见的质量区间）：
  问题: "LangChain的verbose参数有什么作用？"
  上下文: "设置verbose=True可以在控制台输出详细的链执行日志，包括每一步的输入输出，便于调试和排查问题。"
  回答: "verbose=True可以输出调试信息，帮助开发者查看运行过程。"
  参考答案: "verbose=True用于启用详细日志模式，在控制台打印链执行过程中每个步骤的完整输入输出内容，主要用于开发阶段的调试和问题排查。"
  评分: {{"faithfulness": 0.65, "answer_relevance": 0.60, "completeness": 0.50, "reason": "回答方向正确且基于上下文无幻觉，但表述过于简略，未说明日志包含'输入输出'、'每步细节'等关键信息，完整性不足"}}

示例 3 — 低分案例（0.20 以下区域，仅当回答严重偏离或完全无关时出现）：
  问题: "FAISS支持哪些索引类型？"
  上下文: "FAISS支持Flat索引（暴力搜索）、IVF索引（倒排文件加速）和HNSW索引（图结构检索）。"
  回答: "FAISS是一个高效的向量检索库，广泛应用于AI系统，能加速搜索和推荐。"
  参考答案: "FAISS支持Flat索引、IVF索引和HNSW索引三种类型。"
  评分: {{"faithfulness": 0.20, "answer_relevance": 0.20, "completeness": 0.05, "reason": "回答没有基于上下文中的具体索引信息，泛泛而谈未回答问题核心，完全未覆盖具体索引类型"}}

【评分重要提示】：绝大多数真实 RAG 系统的回答质量在 0.30~0.85 之间。请务必在该区间内给出有区分度的评分，不要非 0 即 1。只有检索完全失败、回答完全不相关时才可以打 0 分；只有完美复现所有细节时才可以打 1 分。请参照上述三个标尺示例，根据实际质量在对应区间内精确打分。

--- 以下是正式评分内容 ---

【用户问题】: {query}
【检索到的上下文】: {context}
【系统生成的回答】: {answer}
【黄金标准参考答案】: {ground_truth}

请分别针对以下三个维度给出 0.0 到 1.0 之间的浮点数评分（保留两位小数）：

1. faithfulness (忠实度)：系统回答是否【完全严格基于】检索到的上下文？有没有瞎编或夹带上下文里没有的内容？完全基于上下文给 1.0，有幻觉视程度扣分（参照标尺示例，大部分回答在 0.3~0.9 之间）。
2. answer_relevance (回答相关性)：系统回答是否直接、精准地解答了用户的问题？有没有答非所问或兜圈子？完美解答给 1.0（参照标尺示例，大部分回答在 0.3~0.9 之间）。
3. completeness (答案完整性)：与参考答案对比，系统回答覆盖了几个关键要点和信息？完全覆盖给 1.0，严重缺失扣分（参照标尺示例，大部分回答在 0.2~0.8 之间）。

必须严格按照以下 JSON 格式输出，不要包含任何 markdown 标记：
{{
    "faithfulness": 0.95,
    "answer_relevance": 0.88,
    "completeness": 0.72,
    "reason": "一句话简述评分理由"
}}"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0  # 阅卷标准完全一致，保证可复现
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"⚠️ 裁判打分失败 (API异常): {e}")
        return None  # 返回 None 表示此次评分无效，上层排除

# ==================== 优化版 run_comprehensive_evaluation ====================
def run_comprehensive_evaluation(dataset_path, rerank_limit=45):
    """
    优化点：
    1. LLM-as-Judge 异常数据（None）不计入统计，单独汇报
    2. 完整评估原始数据保存到 evaluation_results.json，可追溯每个 case
    3. 大盘增加异常统计和 completeness 维度
    """
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"未找到黄金测试集: {dataset_path}")
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    total = len(dataset)

    # 统计容器
    retrieval_hits = 0
    mrr_scores = []
    ttft_list = []
    total_latency_list = []
    faithfulness_scores = []
    relevance_scores = []
    completeness_scores = []
    judge_failures = 0  # LLM-as-Judge API 调用异常计数
    raw_results = []     # 每个 case 的原始评估数据

    print(f"\n{'=' * 20} 🏢 启动 RAG 评测 (水位线 LIMIT={rerank_limit}) {'=' * 20}")

    for idx, case in enumerate(dataset):
        query = case["question"]
        expected_id = case["expected_dad_id"]
        ground_truth = case["ground_truth"]

        # ---------------- 1. 检索层评测 ----------------
        t_start = time.time()
        retrieved_docs = asyncio.run(
            zhaohui_and_rerank({"input": query}, rerank_limit=rerank_limit, return_documents=True)
        )
        is_hit = False
        rank_score = 0.0
        hit_rank = -1  # 命中时的排名位置（从 0 开始）
        combined_context_text = ""
        for rank_idx, doc in enumerate(retrieved_docs):
            source_file = os.path.basename(doc.metadata.get('source', '未知文件'))
            page_num = doc.metadata.get('page', 0) + 1
            combined_context_text += f"--- 文档片段 {rank_idx + 1} (来源: {source_file} | 页码: 第 {page_num} 页) ---\n"
            combined_context_text += doc.page_content.strip() + "\n\n"
            if not is_hit and doc.metadata.get("dad_id") == expected_id:
                is_hit = True
                rank_score = 1.0 / (rank_idx + 1)
                hit_rank = rank_idx + 1
        if is_hit:
            retrieval_hits += 1
        mrr_scores.append(rank_score)

        # ---------------- 2. 工程层评测（流式传输掐表） ----------------
        ttft_clock = None
        stream_gen = rag_stream_generate(query, combined_context_text)
        generated_answer = ""
        for chunk in stream_gen:
            if ttft_clock is None:
                ttft_clock = time.time()
            generated_answer += chunk
        t_end = time.time()
        ttft_ms = (ttft_clock - t_start) * 1000 if ttft_clock else 0
        total_latency_ms = (t_end - t_start) * 1000
        ttft_list.append(ttft_ms)
        total_latency_list.append(total_latency_ms)

        # ---------------- 生成层评测（大模型阅卷） ----------------
        judge_res = llm_judge_metrics(query, combined_context_text, generated_answer, ground_truth)

        if judge_res is None:
            judge_failures += 1
            faith_val = None
            relev_val = None
            compl_val = None
            judge_reason = "LLM-as-Judge API 调用失败"
        else:
            faith_val = judge_res.get("faithfulness", 0.0)
            relev_val = judge_res.get("answer_relevance", 0.0)
            compl_val = judge_res.get("completeness", 0.0)
            judge_reason = judge_res.get("reason", "")
            if faith_val is not None:
                faithfulness_scores.append(faith_val)
            if relev_val is not None:
                relevance_scores.append(relev_val)
            if compl_val is not None:
                completeness_scores.append(compl_val)

        # 记录原始评估数据
        case_result = {
            "id": case["id"],
            "question": query,
            "expected_dad_id": expected_id,
            "source_file": case.get("source_file", ""),
            "retrieval_hit": is_hit,
            "hit_rank": hit_rank,
            "mrr_score": rank_score,
            "ttft_ms": ttft_ms,
            "total_latency_ms": total_latency_ms,
            "generated_answer": generated_answer,
            "ground_truth": ground_truth,
            "faithfulness": faith_val,
            "answer_relevance": relev_val,
            "completeness": compl_val,
            "judge_reason": judge_reason
        }
        raw_results.append(case_result)

        # 控制台进度输出（紧凑单行）
        hit_mark = "√" if is_hit else "×"
        f_str = f"F:{faith_val:.2f}" if faith_val is not None else "F:---"
        r_str = f"R:{relev_val:.2f}" if relev_val is not None else "R:---"
        c_str = f"C:{compl_val:.2f}" if compl_val is not None else "C:---"
        bar = "█" * int((idx + 1) / total * 20)
        print(f"  [{idx + 1:>2}/{total}] {hit_mark}  {f_str}  {r_str}  {c_str}  {bar}")

    # ---------------- 汇总全栈大盘数据 ----------------
    n_ttft = len(ttft_list)
    n_lat = len(total_latency_list)

    hit_rate = (retrieval_hits / total) * 100
    mrr = sum(mrr_scores) / total
    avg_ttft = sum(ttft_list) / n_ttft
    avg_lat = sum(total_latency_list) / n_lat
    avg_faith = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 0
    avg_relev = sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0
    avg_compl = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0

    print(f"""
   ╔══════════════════════════════════════════════╗
   ║         RAG 系统综合评估报告                 ║
   ╠══════════════════════════════════════════════╣
   ║                                              ║
   ║  ┌─ 检索质量 ──────────────────────────┐    ║
   ║  │  Hit Rate @5   {hit_rate:>6.1f} %               │    ║
   ║  │  MRR @5        {mrr:>6.3f}                   │    ║
   ║  └──────────────────────────────────────┘    ║
   ║                                              ║
   ║  ┌─ 工程性能 ──────────────────────────┐    ║
   ║  │  TTFT 首字延迟   {avg_ttft:>6.0f} ms            │    ║
   ║  │  端到端延迟      {avg_lat:>6.0f} ms            │    ║
   ║  └──────────────────────────────────────┘    ║
   ║                                              ║
   ║  ┌─ 生成质量 (LLM-as-Judge) ───────────┐    ║
   ║  │  忠实度        {avg_faith:>6.2f}  幻觉控制      │    ║
   ║  │  答案相关性    {avg_relev:>6.2f}  问题匹配度    │    ║
   ║  │  答案完整性    {avg_compl:>6.2f}  vs参考答案    │    ║
   ║  └──────────────────────────────────────┘    ║
   ║                                              ║
   ╚══════════════════════════════════════════════╝""")

    if judge_failures > 0:
        print(f"  ⚠  LLM-Judge 异常 {judge_failures}/{total} 条，已排除")

    # ---------------- 结果解读与优化建议 ----------------
    print(f"  ┌─ 诊断分析 ──────────────────────────────┐")

    # 检索诊断
    if hit_rate >= 80:
        print(f"  │  检索: ✓ 良好 ({hit_rate:.0f}%)，多数问题能找到对应文档    │")
    elif hit_rate >= 50:
        print(f"  │  检索: △ 一般 ({hit_rate:.0f}%)，近半数问题检索未命中       │")
        print(f"  │     → 建议: 检查 chunk 分割粒度或调整混合检索权重  │")
    else:
        print(f"  │  检索: ✗ 较差 ({hit_rate:.0f}%)，需要排查检索链路           │")
        print(f"  │     → 建议: 检查 embedding 模型是否匹配文档语言    │")

    # 忠实度 vs 相关性 交叉诊断
    if avg_faith > 0.7 and avg_relev < 0.5:
        print(f"  │  生成: 高忠实度({avg_faith:.2f})+低相关性({avg_relev:.2f})      │")
        print(f"  │     → 说明检索到的文档本身准确但不匹配问题        │")
        print(f"  │     → 优化重点在检索端，生成端问题不大            │")
    elif avg_faith < 0.5:
        print(f"  │  生成: 忠实度偏低({avg_faith:.2f})，存在幻觉风险              │")
        print(f"  │     → 建议: 强化 system prompt 的约束力           │")
    else:
        print(f"  │  生成: 忠实度({avg_faith:.2f})与相关性({avg_relev:.2f})均衡          │")

    # 时延诊断
    if avg_ttft > 5000:
        print(f"  │  时延: TTFT {avg_ttft:.0f}ms 偏高，用户感知较慢              │")
        print(f"  │     → 建议: 减少重写查询数量或降低召回上限        │")
    else:
        print(f"  │  时延: TTFT {avg_ttft:.0f}ms，在可接受范围内                │")

    print(f"  └──────────────────────────────────────────┘\n")

    # ---------------- 保存评估原始数据 ----------------
    results_path = os.path.join(LOCAL_DB_PATH, "evaluation_results.json")
    summary = {
        "dataset_path": dataset_path,
        "total_cases": total,
        "judge_failures": judge_failures,
        "retrieval": {
            "hit_rate_at_5": (retrieval_hits / total) * 100,
            "mrr_at_5": sum(mrr_scores) / total
        },
        "engineering": {
            "avg_ttft_ms": sum(ttft_list) / n_ttft,
            "avg_latency_ms": sum(total_latency_list) / n_lat
        },
        "generation": {
            "avg_faithfulness": sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else None,
            "avg_answer_relevance": sum(relevance_scores) / len(relevance_scores) if relevance_scores else None,
            "avg_completeness": sum(completeness_scores) / len(completeness_scores) if completeness_scores else None
        },
        "cases": raw_results
    }
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"📁 评估原始数据已保存至: {results_path}")


if __name__ == "__main__":
    DATASET_PATH = os.path.join(LOCAL_DB_PATH, "golden_dataset.json")
    run_comprehensive_evaluation(DATASET_PATH, rerank_limit=45)
