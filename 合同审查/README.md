# 合同审查 AGENT · 企业级合同合规智能审查系统 (v2.0)

基于 **FastAPI + Vue 3 + Tailwind CSS + OOXML Lite + LM Studio / 端侧大模型** 的企业级合同合规智能审查、风险诊断与原生 Word 修订批注导出系统。同时提供 **WorkBuddy stdio MCP 工具**（`contract-reviewer`），在 WorkBuddy 对话中拖入合同即可直接审查。

专为解决企业合同审查中**商业秘密上云泄露风险、传统大模型审查缺乏法律事实与判例支撑、审查意见停留在纯文本无法直接回填到 Word 原文档、以及审查标准不统一**等核心业务痛点而设计。

> 新电脑部署见 `../部署指南.md`。本项目与 kb-tool 互相独立，可单独部署。

---

## 🤖 WorkBuddy MCP 工具（contract-reviewer）

`mcp_server.py` 提供共 **10 个工具**，分双轨运行：

| 轨道 | 工具 | 说明 |
|---|---|---|
| 轻量轨（纯规则引擎，零 LLM 依赖，秒级） | `scan_clause_risk` `lookup_statute` `search_precedent` `detect_contract_type` `get_clause_rewrite` | 实现 `contract/mcp_tools.py`，不依赖 LM Studio |
| 完整轨（LLM 深度审查，需 LM Studio） | `review_contract` `review_contract_file` `export_annotated_docx` `draft_new_contract` | 返回审查摘要 + 原文件同目录自动生成 Word 红线批注版 |
| 诊断 | `ping` | 环境体检验测（LM Studio 在线状态 / 可用模型 / 处理指引） |

**一键接入**：进入本项目文件夹双击 `一键安装到WorkBuddy.bat`（等效
`python install_to_workbuddy.py`），幂等完成 venv/依赖安装、mcp.json 注册、
Skill 部署（`deploy/skills/contract-review`）、用户记忆路由规则写入，以及
**端到端体检**（真实启动 MCP → 握手计时 → 列工具 → 调 `ping` 环境检测）。
可选参数 `--mcp-only`、`--no-verify`。安装后唯一手动步骤：WorkBuddy 连接器页对
`contract-reviewer` 点一次「信任」。

---

## 🛠️ 系统全景架构

```mermaid
flowchart TD
    User(["法务 / 业务人员 (Vue 3 现代 SaaS 工作台)"]) -->|HTTP / SSE 流式通信| Gateway["FastAPI 统一网关 (app/main.py)"]
    
    subgraph Frontend ["前端交互与渲染 (frontend/dist/index.html)"]
        WorkBench["三栏分步协同工作台"]
        WorkBench --> Left["左侧: 审查配置 / 示范合同样本 / 多立场选择"]
        WorkBench --> Mid["中间: 合同正文 / 风险条款原位高亮"]
        WorkBench --> Right["右侧: 风险看板 / 审查意见 / 判例匹配 / Word导出"]
    end

    subgraph AgentEngine ["自主智能体审查状态机 (contract/agent.py)"]
        Gateway --> Parser["合同结构化拆条 (contract/clause_splitter.py)"]
        Parser --> Sense["1. 感知层: 提取条款实体、违约金比例、权责关系"]
        Sense --> Planner["2. 规划层: 条款级分诊决策器 (contract/planner.py)"]
        
        Planner -- "核心争议条款" --> DeepDive["deep_dive 深度多轮推理"]
        Planner -- "标准履约条款" --> QuickScan["quick_scan 快速合规比对"]
        Planner -- "中性常规条款" --> SafePass["skip 安全放行 (节约算力)"]
        
        DeepDive & QuickScan --> Action{"3. 行动层: 工具链分发 (contract/tools.py)"}
        
        Action --> ToolGates["special_gates (16类业务专项审查门禁)"]
        Action --> ToolPrec["precedents (32项最高院司法裁判指引)"]
        Action --> ToolStat["statutes (《民法典》法条真伪与案号比对)"]
        Action --> ToolRules["rule_cards (霸王条款离线安全网兜底)"]
        
        ToolGates & ToolPrec & ToolStat & ToolRules --> Reflect["4. 反思层: 评级矛盾自愈与法条案号校准"]
    end

    subgraph DocumentWriter ["Word 原生修订批注生成器 (contract/document_annotator.py)"]
        Reflect --> OOXML["OOXML Lite 引擎 (contract/ooxml_lite.py)"]
        OOXML --> Docx["原生 .docx 文档 (Word 原生 Track Changes + Comments 批注框)"]
    end
```

---

## 🔥 核心特性与技术亮点

1. **四阶段自主 Agent 闭环状态机 (Perceive-Plan-Act-Reflect Loop)**：
   - **感知 (Perception)**：由 `clause_splitter.py` 将合同结构化拆条，提取违约金、管辖权、知识产权归属等关键要素；
   - **规划 (Planning)**：由 `planner.py` 实施条款级自主分诊（`deep_dive` 深度审查、`quick_scan` 快速扫描、`skip` 安全放行），兼顾深度与高吞吐；
   - **行动 (Action)**：由 `tools.py` 动态调度 16 类专项门禁、32 项最高院判例库、民法典法条校验器与离线规则卡片；
   - **反思 (Reflection)**：自动检视审查结论与证据链的一致性，智能自愈评级矛盾，坚决杜绝大模型法条幻觉与事实脱节。

2. **企业级现代 SaaS 交互设计 (Modern SaaS Workbench)**：
   - 采用国际流行 SaaS 设计语言（Slate 调色板、圆角卡片、高对比度微渐变、清晰层次排版）。
   - 风险分级雷达标记：高危（红色）、中危（橙色）、低危（黄色）、放行（绿色），风险要点与原位条款智能关联。
   - 深度纯净清洗机制：彻底剔除前端多余的 Markdown、反引号、代码块残留，阅读体验丝滑清爽。

3. **100% 物理隔离与本地隐私计算 (Zero Data Leakage)**：
   - 专为企业核心商业合同、投资协议、保密协议打造。
   - 默认对接 `LM Studio` / 本地端侧推理服务（默认接入 `http://127.0.0.1:1234/v1`），审查全过程数据不离开本地物理设备。

4. **16 大类专项审查门禁与深水区条款深挖**：
   - 覆盖**股权转让与投资合伙、业绩对赌与补偿、反稀释保护、商业租赁、软件开发交付、买卖购销、劳动用工与保密竞业**等核心场景。
   - 自动识别隐蔽性极强的深水区免责套路、无限连带责任、违约金倒挂等不平等条款。

5. **32 项最高人民法院/裁判文书网法条判例知识库**：
   - 融合《中华人民共和国民法典》、《最高人民法院关于适用〈民法典〉合同编通则若干问题的解释》以及代表性司法裁判指引。
   - 审查意见自动附带**司法案号**与**裁判规则**（例如违约金过高司法酌减 30% 裁判规则、业绩对赌回购认定标准等），权威可信。

6. **真正的 Word 原生修订与批注导出 (OOXML Native Track Changes & Comments)**：
   - 业界突破性轻量级方案，无需配置复杂的外部渲染服务或依赖 Office 进程。
   - 基于纯 Python 实现的 OOXML 语法树操作，将审查修改建议直接转换为 Word 原生**删除线 (`<w:del>`)、插入线 (`<w:ins>`) 与边栏气泡批注 (`<w:comment>`)**。
   - 导出的 Word 文档在 Microsoft Word、WPS 中打开时，法务可直接点击“接受所有修订”或“逐项审阅批注”，无缝嵌入企业流转协同。

7. **三国立场切换与合同起草功能**：
   - 支持**【偏向甲方 (买方/委托方)】**、**【偏向乙方 (卖方/服务方)】**、**【客观中立 (法官/公证视角)】**三种立场深度审视。
   - 支持提供需求大纲一键自动起草严密标准的合同样本。

---

## 📂 项目目录结构

```
合同审查/
├── mcp_server.py                  # [MCP] stdio MCP 服务入口（10 工具，握手先行、重库懒加载）
├── install_to_workbuddy.py        # [MCP] WorkBuddy 一键安装脚本（venv/注册/Skill/记忆/体检）
├── 一键安装到WorkBuddy.bat        # [MCP] 双击一键接入 WorkBuddy
├── deploy/skills/contract-review/SKILL.md   # [MCP] 随项目分发的对话路由路标
│
├── run.py                         # [Web] 系统一键启动入口 (FastAPI + Uvicorn + 自动打开浏览器)
├── 一键启动.bat                   # [Web] Windows 环境双击一键极速启动脚本
├── config.py                      # 统一运行时配置文件 (端口 8020 / LM Studio 接入配置)
├── README.md                      # 系统架构与使用指南
├── requirements.txt               # Python 依赖清单
├── .env.example                   # 环境变量配置参考范本
├── .gitignore                     # Git 忽略规则
├── sample_contract.py             # 内置真实商业合同样本集 (股权/租赁/软件/劳动)
│
├── app/                           # FastAPI 服务层
│   ├── main.py                    # API 路由装配、CORS 配置与前端静态资源挂载
│   ├── schemas.py                 # Pydantic 请求与响应数据结构契约
│   └── routes/
│       └── contract.py            # 审查、流式推理、判例检索与 Word 批注导出路由
│
├── contract/                      # 智能体核心算法与风控逻辑层
│   ├── mcp_tools.py               # [MCP] 轻量轨 5 工具（纯规则引擎，零 LLM 依赖）
│   ├── agent.py                   # [Agent 核心] 感知→规划→行动→反思四阶段自主闭环状态机
│   ├── planner.py                 # [规划层] 条款级分诊决策器（deep_dive / quick_scan / skip）
│   ├── clause_splitter.py         # [感知层] 合同结构化拆条与特征提取引擎
│   ├── rule_cards.py              # [规则安全网] 离线高危霸王条款穿透与交叉验证兜底
│   ├── statutes.py                # [法条核验] 法律引用真伪与案号一致性核查
│   ├── tools.py                   # [行动层] Agent 工具箱与动态调用分发
│   ├── engine.py                  # 审查流程调度中枢与多轮推理管线
│   ├── parser.py                  # 混合文本与段落结构化解析器
│   ├── prompts.py                 # 针对法务立场的防御性系统提示词工程
│   ├── precedents.py              # 32 项最高院裁判指引与司法案例库
│   ├── ooxml_lite.py              # 轻量级 OOXML 批注与修订语法底层引擎
│   ├── document_annotator.py      # Word 批注封装与字节流导出器
│   ├── data/                      # 预置标准条款与风控标签字典
│   │   ├── clause_standards.csv
│   │   ├── contract_types.csv
│   │   ├── review_checklists.csv
│   │   └── risk_labels.csv
│   └── gates/                     # 16 类专项审查门禁与条款级深水区门禁
│       └── special_gates.py
│
├── frontend/                      # 现代 SaaS 交互工作台前端
│   └── dist/
│       ├── index.html             # 单页现代 SaaS 工作台 (Vue 3 + Tailwind + Element Plus，支持 Agent 思考与分诊轨迹)
│       └── marked.min.js          # 本地 Markdown 解析脚本
│
└── tests/                         # 自动化测试与质量检验套件
    ├── verify_all.py              # 核心模块自动化集成测试脚本
    ├── test_agent_plan.py         # Agent 规划层单测（评分矛盾裁决、预算裁剪、兜底）
    ├── test_agent_loop_guard.py   # Agent 预算守卫与自愈循环单测
    ├── test_agent_reflect.py      # Agent 反思层单测（法条核查、交叉比对）
    ├── test_reasoning.py          # 完整轨审查推理链路测试
    ├── test_stream_debug.py       # 流式输出调试测试
    ├── test_contract_review.py    # 审查逻辑单元测试
    ├── test_annotator.py          # Word 批注导出功能验证
    ├── test_api.py / test_api_endpoints.py   # FastAPI 接口自动化用例
    ├── test_lmstudio_conn.py      # LM Studio 本地服务连通性测试
    └── test_universal_audit.py    # 通用风控规则测试
```

---

## 🚀 快速启动与自举说明

### 1. 前置条件与环境准备
- **Python 环境**：建议 **Python 3.11 – 3.13**（安装时请务必勾选 `Add Python to PATH` 以及 `Install launcher for all users (py)`）。
- **推理服务**：
  - **本地模式（推荐）**：后台启动 **LM Studio**，加载大模型（如 `qwen3.8-27b` 或 `qwen2.5-14b`），并在 1234 端口开启 Local Server。
  - **云端模式**：工作台支持在线切换至 DeepSeek 等云端大模型 API。

### 2. 一键自举启动 (推荐)
- 直接在文件管理器中双击运行 **`一键启动.bat`**。
- **自举特性**：
  - 脚本将优先调用 `py -3`（防御微软商店假占位符）；
  - 自动检测并创建本项目专属的独立的 `.venv` 虚拟环境；
  - 自动安装并补全所有依赖组件（包含 `FastAPI`, `PyMuPDF`, `python-multipart`, `python-docx` 等）；
  - 随后自动拉起服务并在浏览器中打开工作台：`http://localhost:8020`。
  - 具备严格幂等性，日常反复双击秒级启动。

### 3. 命令行启动
```bash
cd 合同审查
# 激活虚拟环境后运行
.venv\Scripts\python run.py
```

---

## 🧪 自动化测试与验证

项目提供了一体化自动化验证套件，覆盖门禁路由、判例检索、Word 原生批注导出、接口可用性等全流程：

```bash
python tests/verify_all.py
```

执行后将运行以下 5 大测试项并报告结果：
1. `[1]` 验证 16 类专项门禁与条款级深水区门禁路由
2. `[2]` 验证判例库与检索召回 (32 项司法判例)
3. `[3]` 验证 Word 原生 Track Changes 批注导出 (带风险条款标注)
4. `[4]` 验证 Word 原生批注导出 (无风险绿标放行)
5. `[5]` 验证 FastAPI 核心接口与静态前端挂载
