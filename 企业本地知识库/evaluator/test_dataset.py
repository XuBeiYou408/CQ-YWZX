import os
import json
import random
from openai import OpenAI
from rag.vector_store import safe_all_wenjian
from config import LOCAL_DB_PATH


client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_API_URL")
)

# ==================== 原版 build_golden_dataset（注释保留） ====================
# def build_golden_dataset(sample_size=30):
#     print(f"📊 当前本地知识库总片段数: {len(safe_all_wenjian)}")
#
#     # 防御编程：如果片段太少，调小采样量
#     actual_sample_size = min(sample_size, len(safe_all_wenjian))
#
#     # 随机抽取指定数量的文档片段来出题，保证测试集的广泛度和随机性
#     sampled_docs = random.sample(safe_all_wenjian, actual_sample_size)
#
#     golden_dataset = []
#     print(f"🤖 正在调用 DeepSeek 逆向生成 {actual_sample_size} 条黄金测试数据...")
#
#     for idx, doc in enumerate(sampled_docs):
#         # 提取当前片段的内容，以及我们在第三步注入的父块关联信息
#         context = doc.page_content
#         dad_id = doc.metadata.get("dad_id", "unknown_source")
#         source = doc.metadata.get("source", "unknown_file")
#
#         system_prompt = "你是一个严谨的学术考试出题官。请基于用户给出的文档片段，反向生成一道高质量、针对具体技术细节的问答题，并给出标准答案。必须严格基于文本，不得瞎编。"
#         user_prompt = f"""请阅读以下文档片段，生成一个用户可能会提出的【高质量技术问题】以及对应的【标准参考答案】。
#
# 【文档片段】：
# \"\"\"
# {context}
# \"\"\"
#
# 【硬性输出格式要求】：
# 你必须以标准 JSON 格式输出，不要包含任何 markdown 标记（如 ```json）。键值对格式如下：
# {{
#     "question": "针对该片段生成的、具体的、描述清晰的技术问题",
#     "ground_truth": "结合该片段给出的详尽、准确的标准参考答案"
# }}"""
#
#         try:
#             response = client.chat.completions.create(
#                 model="deepseek-chat",
#                 messages=[
#                     {"role": "system", "content": system_prompt},
#                     {"role": "user", "content": user_prompt}
#                 ],
#                 response_format={"type": "json_object"},
#                 temperature=0.3  # 低随机性，保证出题严谨贴合原文
#             )
#
#             # 解析返回的 JSON 字符串
#             raw_res = response.choices[0].message.content
#             qa_pair = json.loads(raw_res)
#
#             # 将题目、标准答案与它在物理硬盘上的"定位锚点"强绑定
#             test_case = {
#                 "id": f"test_{idx:03d}",
#                 "question": qa_pair["question"],
#                 "ground_truth": qa_pair["ground_truth"],
#                 "expected_dad_id": dad_id,  # 这个题目的正确答案在哪，由这个ID说了算
#                 "source_file": os.path.basename(source)
#             }
#
#             golden_dataset.append(test_case)
#             print(f"✅ [{idx + 1}/{actual_sample_size}] 成功为文件 {test_case['source_file']} 生成考题。")
#
#         except Exception as e:
#             print(f"⚠️ 第 {idx + 1} 个片段生成考题失败: {e}")
#             continue
#
#     output_path = os.path.join(LOCAL_DB_PATH, "golden_dataset.json")
#     with open(output_path, "w", encoding="utf-8") as f:
#         json.dump(golden_dataset, f, ensure_ascii=False, indent=4)
#
#     print(f"🎉 黄金测试集构建完毕！共 {len(golden_dataset)} 道高价值考题。已保存至: {output_path}")
#     return output_path


# ====================  build_golden_dataset ====================
def build_golden_dataset(sample_size=30):
    """
    优化点：
    1. 固定 random.seed(42)，保证每次生成的测试集完全相同（可复现）
    2. 过滤太短或无意义的文档片段（< 50 字符），确保出题素材有足够信息量
    3. 生成后校验 QA 质量（question > 10 字符, ground_truth > 20 字符）
    4. 失败自动重试（最多 3 次），提高数据集生成成功率
    """
    random.seed(42)

    # 过滤太短的片段（目录页、免责声明等无出题价值的内容）
    MIN_CHUNK_LENGTH = 50
    valid_docs = [doc for doc in safe_all_wenjian if len(doc.page_content.strip()) >= MIN_CHUNK_LENGTH]

    print(f"📊 当前本地知识库总片段数: {len(safe_all_wenjian)}")
    print(f"📊 过滤后有效片段数（≥{MIN_CHUNK_LENGTH}字符）: {len(valid_docs)}")

    if len(valid_docs) == 0:
        print("❌ 没有足够长的有效片段，无法生成测试集")
        return None

    actual_sample_size = min(sample_size, len(valid_docs))
    sampled_docs = random.sample(valid_docs, actual_sample_size)

    golden_dataset = []
    MAX_RETRIES = 3
    print(f"🤖 正在调用 DeepSeek 逆向生成 {actual_sample_size} 条黄金测试数据...")

    for idx, doc in enumerate(sampled_docs):
        context = doc.page_content
        dad_id = doc.metadata.get("dad_id", "unknown_source")
        source = doc.metadata.get("source", "unknown_file")

        system_prompt = "你是一个严谨的学术考试出题官。请基于用户给出的文档片段，反向生成一道高质量、针对具体技术细节的问答题，并给出标准答案。必须严格基于文本，不得瞎编。"
        user_prompt = f"""请阅读以下文档片段，生成一个用户可能会提出的【高质量技术问题】以及对应的【标准参考答案】。

【文档片段】：
\"\"\"
{context}
\"\"\"

【硬性输出格式要求】：
你必须以标准 JSON 格式输出，不要包含任何 markdown 标记（如 ```json）。键值对格式如下：
{{
    "question": "针对该片段生成的、具体的、描述清晰的技术问题",
    "ground_truth": "结合该片段给出的详尽、准确的标准参考答案"
}}"""

        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3
                )

                raw_res = response.choices[0].message.content
                qa_pair = json.loads(raw_res)

                question = qa_pair.get("question", "").strip()
                ground_truth = qa_pair.get("ground_truth", "").strip()

                # QA 质量校验：问题不能太短，答案不能太短
                if len(question) < 10:
                    raise ValueError(f"生成的问题太短（{len(question)}字符），质量不合格")
                if len(ground_truth) < 20:
                    raise ValueError(f"生成的答案太短（{len(ground_truth)}字符），质量不合格")

                test_case = {
                    "id": f"test_{len(golden_dataset):03d}",
                    "question": question,
                    "ground_truth": ground_truth,
                    "expected_dad_id": dad_id,
                    "source_file": os.path.basename(source)
                }

                golden_dataset.append(test_case)
                print(f"✅ [{len(golden_dataset)}/{actual_sample_size}] 文件 {test_case['source_file']} 生成考题（第 {attempt} 次尝试）。")
                success = True
                break

            except (json.JSONDecodeError, ValueError) as e:
                print(f"⚠️ 片段 {idx + 1} 第 {attempt}/{MAX_RETRIES} 次失败（数据质量）: {e}")
            except Exception as e:
                print(f"⚠️ 片段 {idx + 1} 第 {attempt}/{MAX_RETRIES} 次失败（API调用）: {e}")

        if not success:
            print(f"❌ 片段 {idx + 1} 经过 {MAX_RETRIES} 次重试仍失败，已跳过")

    output_path = os.path.join(LOCAL_DB_PATH, "golden_dataset.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(golden_dataset, f, ensure_ascii=False, indent=4)

    print(f"\n🎉 黄金测试集构建完毕！共 {len(golden_dataset)} 道高价值考题。已保存至: {output_path}")
    print(f"   成功率: {len(golden_dataset)}/{actual_sample_size} ({len(golden_dataset) / actual_sample_size * 100:.1f}%)")
    return output_path


if __name__ == "__main__":
    build_golden_dataset(sample_size=20)
