# -*- coding: utf-8 -*-
"""
规则化结构化提取 · 多格式回归自测
=====================================
用途：验证「零算力规则化结构化提取」对**不同版式**的简历都能正确提取，
      而不是只适配某一份测试简历。改动 app/core/screening.py 的提取规则后请务必跑一遍。

运行（必须用项目自己的解释器）：
    .venv\\Scripts\\python.exe tools\\selftest_resume_struct.py

退出码：0 = 全部通过；1 = 存在失败用例（输出中标记 ✗）
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app.core.screening import build_structured_resume  # noqa: E402


# ────────────────────────────── 用例样本 ──────────────────────────────

# 1) PDF/Word 导出后的硬换行格式：一个字段一行 + 长句断行 + 中英之间插空格
CASE_PDF_WRAPPED = """李明轩
求职意向：AI 应用开发工程师
电话：138-XXXX-6688 | 邮箱：limingxuan@example.com | 现居：重庆渝北

个人简介
3 年AI 应用开发经验，专注于大语言模型（LLM）应用落地、RAG 检索增强系统、智能体
（Agent）架构设计与企业知识库建设。熟悉LangChain/LlamaIndex 等框架。

核心技能
编程语言：Python（熟练）、Java（掌握）、SQL（熟练）
AI框架：LangChain、LlamaIndex、AutoGen
部署运维：Docker、Kubernetes、Nginx、Git、Linux

工作经历
重庆某某科技有限公司 | AI 解决方案部 | AI应用开发工程师
2024.03 - 至今
所属部门：AI解决方案部 | 汇报对象：技术总监
工作内容：
主导企业智能知识库系统开发，基于LangChain + FAISS + BGE Embedding构建RAG检索增强
方案，支持Word/PDF/Excel等多格式文档解析。
工作业绩：年度优秀员工（2024）。

项目经历
企业级RAG知识库平台
2024.06 - 2024.12
项目描述：面向企业内部的智能知识问答平台，支持多格式文档上传、自动切片、向量化存储、
语义检索、多轮对话。
技术栈：Python、FastAPI、LangChain、FAISS、Qwen2.5-14B
个人职责：主导整体架构设计，设计分层切片策略与多路召回融合排序。
项目成果：问答准确率从65%提升至89%，服务公司内部500+员工。

教育背景
重庆大学
计算机科学与技术
本科
2018.09 - 2022.06
主修课程：数据结构、算法设计、操作系统、计算机网络

证书与荣誉
阿里云ACP认证- 人工智能工程师（2024）
全国大学生数学建模竞赛省级一等奖（2021）
"""

# 2) 紧凑单行格式：公司|职位|时间段 一行写完；教育一行写全
CASE_COMPACT = """王小明
求职意向：资深前端开发/全栈工程师
电话：137-8888-6666  |  邮箱：wangxiaoming@example.com  |  现居：深圳

个人简介
6年前端与全栈开发经验，本科软件工程专业，熟悉 React、TypeScript、Node.js。

教育背景
2015.09 - 2019.06  深圳大学  软件工程  本科（统招全日制）  校优秀毕业生

工作经历
某互联网科技有限公司  |  资深前端开发工程师        2021.07 - 至今
所属部门：前端架构组
工作内容：主导企业中台微前端架构改造，首屏加载性能提升 42%，支撑日均 2000 万 PV。
工作业绩：2024 年度优秀员工。

项目经历
企业级微前端基座平台                          2022.03 - 2024.12
项目描述：面向多业务线的统一微前端接入平台。
技术栈：React、TypeScript、qiankun、Webpack5、Docker
我的职责：设计 JS 沙箱与样式隔离方案，落地微应用预加载策略。
项目成果：接入 35 个子系统，发布故障率降低 70%。

证书
大学英语六级（CET-6）、软件设计师（中级）
"""

# 3) 多段学历：硕士 + 本科，各自字段独立成行
CASE_MULTI_DEGREE = """张启航
求职意向：算法工程师
电话：139-2233-4455  |  邮箱：zhangqihang@example.com  |  现居：北京

教育背景
清华大学
软件工程
硕士
2019.09 - 2022.06
北京邮电大学
计算机科学与技术
本科
2015.09 - 2019.06

工作经历
某人工智能研究院  |  算法工程师        2022.07 - 至今
工作内容：负责推荐算法模型迭代与线上效果优化，CTR 提升 12%。

核心技能
编程语言：Python、C++
算法框架：PyTorch、TensorFlow
"""

# 4) 无小节标题的纯文本流（很多系统导出的简历就是这样）
CASE_NO_HEADERS = """李思远
求职意向：后端开发工程师
电话：136-5566-7788  |  邮箱：lisiyuan@example.com  |  现居：杭州

5年Java后端开发经验，熟悉 Spring Boot、MySQL、Redis 与微服务架构。

某科技有限公司  |  高级后端开发工程师        2020.05 - 至今
负责订单中心微服务重构，接口 P99 从 320ms 降到 90ms。
2017.07 - 2020.04  某软件技术有限公司  后端开发工程师
负责用户中心与权限系统开发与维护。

高等教育
2013.09 - 2017.06  杭州电子科技大学  计算机科学与技术  本科（统招全日制）

核心技能
编程语言：Java、SQL、Shell
后端框架：Spring Boot、Spring Cloud、MyBatis
"""

# 5) 别名小节标题：工作履历 / 项目实践 / 技能清单 / 获奖情况
CASE_ALIAS_HEADERS = """赵敏
求职意向：数据分析师

工作履历
某电商有限公司 | 数据分析师 | 2021.03 - 至今
工作内容：搭建用户增长分析看板，GMV 归因模型准确率 92%。

项目实践
用户流失预警模型   2022.01 - 2022.09
项目描述：基于机器学习预测用户流失概率。
技术栈：Python、Pandas、XGBoost、Tableau
项目成果：流失召回率提升 18%。

教育经历
2017.09 - 2021.06  上海财经大学  统计学  本科

技能清单
编程语言：Python、R、SQL
分析工具：Pandas、XGBoost、Tableau

获奖情况
校一等奖学金（2019）
"""

# 6) 实习经历 + 全角符号 + 英文混排
CASE_INTERN_EN = """陈嘉乐
求职意向：前端开发实习生
电话：135-6677-8899  |  邮箱：chenjiale@example.com

实习经历
某网络科技有限公司 ｜ 前端开发实习生 ｜ 2023.07 - 2023.12
工作内容：参与管理后台表格组件开发，使用 Vue3 + TypeScript 完成 12 个业务页面。

教育背景
2020.09—2024.06  南京航空航天大学  软件工程  本科（统招全日制）

核心技能
开发语言：JavaScript、TypeScript、HTML/CSS
前端框架：Vue3、React
"""

# 7) 无冒号的行内小节标题：标题与内容在同一行
CASE_INLINE_HEADER = """周文
求职意向：测试开发工程师

教育背景 2016.09 - 2020.06 电子科技大学 软件工程 本科（统招全日制）
工作经历 2020.07 - 至今 某通信技术有限公司 测试开发工程师
工作内容：负责自动化测试框架搭建，用例执行时长缩短 60%。
核心技能 编程语言：Python、Java、SQL
"""


# ────────────────────────────── 断言工具 ──────────────────────────────

FAILURES = []


def check(desc, ok, detail=""):
    print(f"    {'✓' if ok else '✗'} {desc}" + (f"   -> {detail}" if (detail and not ok) else ""))
    if not ok:
        FAILURES.append(f"{CURRENT} | {desc}" + (f" | {detail}" if detail else ""))


CURRENT = ""


def run_case(name, text, gate=None):
    global CURRENT
    CURRENT = name
    print(f"\n=== 用例: {name} ===")
    fr = build_structured_resume(text, gate or {"detected_exp_years": 5}, "")
    print("    教育:", [(e["school"], e["degree"], e["major"] or "-", e["period"] or "-", e["tier"])
                      for e in fr["educations"]])
    print("    工作:", [(w["company"][:16], w["title"] or "-", w["period"] or "-")
                      for w in fr["work_experience"]])
    print("    项目:", [(p["name"][:18], p["role"], p["period"] or "-")
                      for p in fr["project_experience"]])
    print("    技能:", [m["category"] for m in fr["skills_matrix"]])
    print("    证书/荣誉:", fr["certificates"][:5])

    # 所有用例的通用底线
    for e in fr["educations"]:
        check(f"院校识别非噪声（{e['school']}）", e["school"] not in ("全国大学", "中国大学", "本市大学"))
        check(f"学历字段完整（{e['school']}）",
              e["degree"] != "学历未识别" or not e["school"],
              f"degree={e['degree']}")
    for w in fr["work_experience"]:
        check(f"履历条目无时间段残留（{w['company'][:12]}）",
              not any(ch.isdigit() for ch in w["company"][:4]),
              f"company={w['company']}")
        check(f"履历条目职责非空（{w['company'][:12]}）", bool(w["responsibilities"]) or bool(w["achievements"]))
    for p in fr["project_experience"]:
        check(f"项目名无时间残留（{p['name'][:16]}）",
              not any(ch.isdigit() for ch in p["name"]), f"name={p['name']}")
    return fr


# ────────────────────────────── 各用例断言 ──────────────────────────────

fr = run_case("PDF导出硬换行格式", CASE_PDF_WRAPPED, {"detected_exp_years": 3})
check("识别到 1 段学历", len(fr["educations"]) == 1, str(fr["educations"]))
check("院校=重庆大学", fr["educations"] and fr["educations"][0]["school"] == "重庆大学")
check("学历=本科", fr["educations"] and fr["educations"][0]["degree"] == "本科")
check("专业=计算机科学与技术", fr["educations"] and fr["educations"][0]["major"] == "计算机科学与技术")
check("时间段=2018.09 - 2022.06", fr["educations"] and fr["educations"][0]["period"] == "2018.09 - 2022.06")
check("工作经历 ≥1 段", len(fr["work_experience"]) >= 1)
check("工作经历含部门/职位/时间段",
      bool(fr["work_experience"]) and fr["work_experience"][0]["title"] and fr["work_experience"][0]["period"])
check("项目经历 ≥1 个且名称正确",
      fr["project_experience"] and fr["project_experience"][0]["name"] == "企业级RAG知识库平台")
check("项目技术栈已提取", bool(fr["project_experience"]) and "LangChain" in fr["project_experience"][0]["tech_stack"])
check("技能矩阵 ≥3 类", len(fr["skills_matrix"]) >= 3)
check("荣誉含数学建模竞赛", any("数学建模" in c for c in fr["certificates"]))

fr = run_case("紧凑单行格式", CASE_COMPACT, {"detected_exp_years": 6})
check("识别到 1 段学历", len(fr["educations"]) == 1, str(fr["educations"]))
check("院校=深圳大学 / 专业=软件工程", fr["educations"] and fr["educations"][0]["school"] == "深圳大学"
      and fr["educations"][0]["major"] == "软件工程")
check("荣誉=校优秀毕业生", fr["educations"] and "优秀毕业生" in fr["educations"][0]["honors"])
check("工作经历 1 段且时间段正确",
      len(fr["work_experience"]) == 1 and fr["work_experience"][0]["period"] == "2021.07 - 至今")
check("工作业绩已提取", "优秀员工" in (fr["work_experience"][0]["achievements"] if fr["work_experience"] else ""))
check("项目经历 1 个且名称/时间正确",
      len(fr["project_experience"]) == 1 and fr["project_experience"][0]["name"] == "企业级微前端基座平台"
      and fr["project_experience"][0]["period"] == "2022.03 - 2024.12")
check("技能矩阵 ≥2 类", len(fr["skills_matrix"]) >= 2)

fr = run_case("多段学历（硕士+本科）", CASE_MULTI_DEGREE)
check("识别到 2 段学历", len(fr["educations"]) == 2, str(fr["educations"]))
check("两段学历院校正确",
      [e["school"] for e in fr["educations"]] == ["清华大学", "北京邮电大学"],
      str([e["school"] for e in fr["educations"]]))
check("两段学历层次正确",
      [e["degree"] for e in fr["educations"]] == ["硕士研究生", "本科"],
      str([e["degree"] for e in fr["educations"]]))
check("两段学历专业正确",
      [e["major"] for e in fr["educations"]] == ["软件工程", "计算机科学与技术"],
      str([e["major"] for e in fr["educations"]]))
check("两段学历时间段正确",
      [e["period"] for e in fr["educations"]] == ["2019.09 - 2022.06", "2015.09 - 2019.06"],
      str([e["period"] for e in fr["educations"]]))
check("工作经历 1 段", len(fr["work_experience"]) == 1)

fr = run_case("无小节标题纯文本流", CASE_NO_HEADERS, {"detected_exp_years": 5})
check("教育背景可识别", len(fr["educations"]) >= 1, str(fr["educations"]))
check("院校=杭州电子科技大学", fr["educations"] and fr["educations"][0]["school"] == "杭州电子科技大学")
check("工作经历 ≥1 段", len(fr["work_experience"]) >= 1,
      str([w["company"] for w in fr["work_experience"]]))
check("技能矩阵 ≥2 类", len(fr["skills_matrix"]) >= 2)

fr = run_case("别名小节标题", CASE_ALIAS_HEADERS)
check("工作履历被识别为工作经历", len(fr["work_experience"]) == 1, str(fr["work_experience"]))
check("项目实践被识别为项目经历", len(fr["project_experience"]) == 1)
check("教育经历被识别", len(fr["educations"]) == 1 and fr["educations"][0]["school"] == "上海财经大学")
check("技能清单被识别", len(fr["skills_matrix"]) >= 2)
check("获奖情况被识别", any("奖学金" in c for c in fr["certificates"]), str(fr["certificates"]))

fr = run_case("实习经历+全角符号", CASE_INTERN_EN)
check("实习经历被识别为工作经历", len(fr["work_experience"]) >= 1, str(fr["work_experience"]))
check("实习职位/时间段正确",
      bool(fr["work_experience"]) and "实习生" in (fr["work_experience"][0]["title"] or "")
      and fr["work_experience"][0]["period"] == "2023.07 - 2023.12",
      str(fr["work_experience"][0] if fr["work_experience"] else {}))
check("院校=南京航空航天大学", fr["educations"] and fr["educations"][0]["school"] == "南京航空航天大学")
check("技能矩阵 ≥2 类", len(fr["skills_matrix"]) >= 2)

fr = run_case("无冒号行内小节标题", CASE_INLINE_HEADER)
check("教育背景可识别（行内标题）", len(fr["educations"]) >= 1, str(fr["educations"]))
check("院校=电子科技大学", fr["educations"] and fr["educations"][0]["school"] == "电子科技大学")
check("工作经历可识别（行内标题）", len(fr["work_experience"]) >= 1, str(fr["work_experience"]))


# ────────────────────────────── 汇总 ──────────────────────────────

print("\n" + "=" * 68)
if FAILURES:
    print(f"回归自测未通过：{len(FAILURES)} 项失败")
    for f in FAILURES:
        print("  ✗", f)
    sys.exit(1)
print("回归自测全部通过 ✓")
sys.exit(0)
