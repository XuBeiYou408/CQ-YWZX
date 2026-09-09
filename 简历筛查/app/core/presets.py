"""
预设岗位与候选人数据库 (含现实招聘软件全维度门槛指标与求职者完整原版简历数据)
"""
from typing import Any, Dict, List, Optional

PRESET_JOBS: List[Dict[str, Any]] = [
    {
        "id": "fe-fullstack",
        "title": "资深前端开发/全栈工程师",
        "department": "国际电商架构组",
        "salary": "25-40K·16薪",
        "salary_min": 25,
        "salary_max": 40,
        "salary_months": 16,
        "location": "深圳 · 南山",
        "hc": 2,
        "experience_range": "5-10年",
        "experience_years": 5,
        "education": "bachelor",
        "education_type": "full_time",  # 统招全日制
        "school_tier": "any",          # 院校背景要求
        "major": "computer",           # 计算机/软件相关专业
        "max_age": 35,                 # 年龄偏好: 35岁以下
        "available_status": "any",     # 到岗要求: 不限
        "required_skills": ["React", "TypeScript", "Node.js", "微前端", "高并发架构"],
        "jd": "负责公司核心业务系统前端及全栈架构设计与演进，主导关键技术选型与微前端体系建设。要求熟练精通 React 18、TypeScript 与 Node.js 微服务架构，具备 5 年以上全栈或大型 Web 系统架构实战经验，有千万级 PV 性能调优经验者优先。",
    },
    {
        "id": "llm-engineer",
        "title": "大模型算法工程师",
        "department": "AI创新实验室",
        "salary": "30-50K·15薪",
        "salary_min": 30,
        "salary_max": 50,
        "salary_months": 15,
        "location": "北京 · 中关村",
        "hc": 3,
        "experience_range": "3-5年",
        "experience_years": 3,
        "education": "master",
        "education_type": "full_time",
        "school_tier": "985",
        "major": "computer",
        "max_age": 32,
        "available_status": "month",
        "required_skills": ["Python", "PyTorch", "LLM", "RLHF", "Agent"],
        "jd": "负责前沿大语言模型预训练、指令微调（SFT）与强化学习（RLHF）对齐，探索智能体（Agent）及端到端应用落地。要求统招 985 院校硕士及以上学历，精通 PyTorch 与主流分布式训练框架，有顶会论文或大模型开源贡献者优先。",
    },
    {
        "id": "senior-pm",
        "title": "高级产品经理",
        "department": "企服SaaS产品部",
        "salary": "20-35K·13薪",
        "salary_min": 20,
        "salary_max": 35,
        "salary_months": 13,
        "location": "上海 · 张江",
        "hc": 1,
        "experience_range": "5-10年",
        "experience_years": 5,
        "education": "bachelor",
        "education_type": "full_time",
        "school_tier": "any",
        "major": "any",
        "max_age": 35,
        "available_status": "any",
        "required_skills": ["B端产品", "数据分析", "PRD", "用户增长"],
        "jd": "主导企业级 B 端核心产品的需求洞察、PRD 撰写与全生命周期管理，以数据驱动产品迭代与业务规模化增长。要求统招本科及以上学历，5 年以上复杂业务产品操盘经验。",
    },
]

PRESET_CANDIDATES: List[Dict[str, Any]] = [
    {
        "id": "preset-001",
        "name": "林远志",
        "job_id": "fe-fullstack",
        "age": 31,
        "experience_years": 8,
        "education": "master",
        "school": "浙江大学",
        "school_tier": "985",
        "ai_score": 98,
        "ai_tier": "S",
        "state": "scheduled",
        "salary_expect": "28-35K·16薪",
        "current_company": "腾讯科技 (深圳) 有限公司",
        "current_title": "资深全栈架构师 / 技术组长",
        "skills": ["React", "TypeScript", "Node.js", "微前端", "高并发架构", "Docker"],
        "verified": True,
        "tags": [
            "✓ 8年资历·超额满足JD",
            "✓ 浙大计算机硕·985统招全日制",
            "✓ React/TS/Node/微前端 100%覆盖",
        ],
        "radar": {
            "技术深度": 98,
            "项目规模": 95,
            "技术栈匹配": 100,
            "学历背景": 95,
            "发展潜力": 90,
        },
        "status": "available",
        "available_time": "两周内到岗",
        "apply_time": "2026-03-01 10:30",
        "ai_label": "S级·强烈推荐",
        "ai_reason": "候选人毕业于浙江大学计算机系（985统招硕士），具有8年一线大厂深厚全栈研发资历。曾主导腾讯大型微前端体系搭建与高并发架构治理，核心技能与岗位JD完美重合，技术深度与综合潜力均属顶尖水平，强烈推荐直接安排终面。",
        "interview_questions": [
            "请结合你在腾讯主导微前端架构的实战经历，详细谈谈微应用间的沙箱隔离与通信机制是如何设计的？",
            "针对React高并发/大数据量渲染场景，你有哪些具体的性能调优策略及服务端渲染（SSR）缓存架构设计？",
            "在Node.js微服务中，如何进行系统性内存泄漏排查与高并发事件循环瓶颈优化？",
        ],
        "full_resume": {
            "basic_info": {
                "name": "林远志",
                "gender": "男",
                "age": 31,
                "work_years": 8,
                "city": "广东 · 深圳",
                "phone": "138-0018-8888 (已实名核验)",
                "email": "linyuanzhi.arch@gmail.com",
                "political_status": "中共党员",
                "target_title": "资深前端开发专家 / 全栈架构师",
                "target_salary": "28-35K · 16薪",
                "target_city": "深圳",
                "job_status": "在职 - 考虑更好机会 (2周内到岗)"
            },
            "summary": [
                "8年一线互联网大厂核心架构演进经验，主导过日均千万级PV的企业级微前端基座与Node.js高可用全栈网关研发；",
                "精通 React 18 / TypeScript / Node.js 全栈体系，对底层Fiber调和机制、Web Components及JS沙箱原理有深入源码级理解；",
                "具备从0到1搭建架构规范、Monorepo工程化基建、自动化CI/CD及全链路性能可观测性的成熟操盘经验；",
                "浙江大学计算机系985统招硕本连读，理论功底扎实，曾获国家奖学金与ACM校赛金牌，带过15人技术攻坚团队。"
            ],
            "work_experience": [
                {
                    "company": "腾讯科技 (深圳) 有限公司",
                    "department": "微信商业化与企业中台技术部",
                    "title": "资深全栈开发专家 / 前端架构组负责人",
                    "period": "2021.06 - 至今 (近4年)",
                    "responsibilities": "负责微信生态核心商业化中台及全栈微服务架构设计与演进，管理12人跨端全栈研发团队；主导跨部门微前端治理体系落地，保障亿级业务流量下中台系统的极高可用性与工程交付效能。",
                    "achievements": "主导完成35+个业务子系统的微前端解耦重构，首屏加载性能提升45%，发布故障率降低70%；设计Node.js高并发BFF中间层，顺利护航双十一大促，单日峰值2.8亿次请求零宕机故障。"
                },
                {
                    "company": "北京字节跳动科技有限公司",
                    "department": "飞书协同产品研发部",
                    "title": "高级前端开发工程师",
                    "period": "2018.07 - 2021.05 (近3年)",
                    "responsibilities": "深度参与飞书在线文档编辑器核心渲染引擎及多维表格前端基建；攻坚复杂协同场景下的富文本渲染流畅度与协同冲突解决算法。",
                    "achievements": "设计基于Canvas+DOM混合的高性能数据表格渲染管线，支撑10万行×100列大数据量流畅滑动（稳定60FPS）；主导多版本协同算法优化，协同数据同步延迟降低60%。"
                }
            ],
            "project_experience": [
                {
                    "name": "腾讯大型微前端统一架构与容器治理平台",
                    "role": "核心架构师 & 项目负责人",
                    "period": "2022.03 - 2024.12",
                    "tech_stack": "React 18, TypeScript, qiankun / Wujie, Node.js, Webpack 5, Docker, Kubernetes",
                    "background": "业务线历史遗留系统包含Vue2/React16等异构技术栈，业务耦合极其严重，发版互相阻塞，跨团队联调摩擦大。",
                    "solutions": "自研基于Web Components的DOM隔离与Proxy原生代理JS沙箱；统一设计全局状态分发EventBus与微应用预加载策略；建立微前端性能监控与异常降级容灾切流中枢。",
                    "metrics": "成功平滑接入35个子业务系统，微应用静态资源复用率达60%，业务迭代交付周期从周级缩短至天级，页面白屏率降至0.05%以下。"
                },
                {
                    "name": "千万级高并发全栈数据大屏与BFF服务网关",
                    "role": "全栈技术负责人",
                    "period": "2021.08 - 2022.02",
                    "tech_stack": "Node.js (NestJS), TypeScript, Redis, Kafka, WebSocket, ECharts",
                    "background": "承担营销大促全链路实时交易数据多维大屏监控与报表聚合，峰值瞬时QPS达1.2w+。",
                    "solutions": "采用Node.js多进程Cluster多核复用与Redis分布式多级缓存；基于WebSocket建立高吞吐增量推送信道；使用Backpressure背压机制防止下游服务崩溃。",
                    "metrics": "零宕机平稳支撑业务大促峰值，P99接口响应时间控制在18ms以内，数据实时刷新延迟小于300ms。"
                }
            ],
            "educations": [
                {
                    "school": "浙江大学",
                    "degree": "硕士研究生",
                    "major": "计算机科学与技术",
                    "period": "2015.09 - 2018.06",
                    "tier": "985 / 211 / 双一流 / 统招全日制",
                    "honors": "国家奖学金、浙江大学优秀毕业研究生、ACM程序设计竞赛省级一等奖"
                },
                {
                    "school": "浙江大学",
                    "degree": "本科学士",
                    "major": "软件工程",
                    "period": "2011.09 - 2015.06",
                    "tier": "985 / 211 / 双一流 / 统招全日制",
                    "honors": "连续三年一等奖学金、校优秀三好学生"
                }
            ],
            "skills_matrix": [
                {"category": "前端技术栈", "skills": ["React 18", "TypeScript", "Next.js", "Vue 3", "Webpack / Vite", "TailwindCSS", "Canvas / WebGL"]},
                {"category": "后端与数据库", "skills": ["Node.js", "NestJS", "Express", "Redis", "MySQL", "MongoDB", "Kafka"]},
                {"category": "架构与工程化", "skills": ["微前端体系 (qiankun/无界)", "BFF网关设计", "CI/CD流水线", "Docker / K8s", "高并发与性能极致优化"]}
            ],
            "certificates": [
                "全国计算机技术与软件专业资格证书 · 系统架构设计师 (高级)",
                "大学英语六级 (CET-6 610分，具备无障碍英文技术交流与文档撰写能力)"
            ]
        }
    },
    {
        "id": "preset-002",
        "name": "陈书婷",
        "job_id": "fe-fullstack",
        "age": 28,
        "experience_years": 5,
        "education": "bachelor",
        "school": "华南理工大学",
        "school_tier": "985",
        "ai_score": 91,
        "ai_tier": "A",
        "state": "recommended",
        "salary_expect": "25-30K·15薪",
        "current_company": "Shopee (虾皮信息科技)",
        "current_title": "资深全栈研发工程师",
        "skills": ["TypeScript", "Next.js", "React", "Node.js", "Web Vitals", "SSR"],
        "verified": True,
        "tags": [
            "✓ 5年大厂经验·契合度高",
            "✓ 华南理工985统招全日制本",
            "✓ Next.js与全链路性能调优专家",
        ],
        "radar": {
            "技术深度": 90,
            "项目规模": 88,
            "技术栈匹配": 93,
            "学历背景": 90,
            "发展潜力": 92,
        },
        "status": "available",
        "available_time": "1个月内到岗",
        "apply_time": "2026-03-02 14:15",
        "ai_label": "A级·建议录用",
        "ai_reason": "候选人毕业于985华南理工大学软件工程专业，具备5年知名跨境电商大厂研发经验，技术栈高度契合。在Next.js企业级架构与Web全链路性能极致优化方面具备丰富落地经验，工程规范度高，建议推进面试。",
        "interview_questions": [
            "在Shopee跨国弱网环境下，你们是如何利用Next.js进行首屏渲染优化和静态资源边缘分发的？",
            "请深入谈谈TypeScript高级类型（如条件类型、映射类型）在企业级通用组件库中的设计与约束实践。",
            "针对高频动态更新与大数据量交互场景，如何做前端指标量化（如FCP、LCP、CLS）及系统化治理？",
        ],
        "full_resume": {
            "basic_info": {
                "name": "陈书婷",
                "gender": "女",
                "age": 28,
                "work_years": 5,
                "city": "广东 · 广州",
                "phone": "139-0022-7777 (已实名核验)",
                "email": "shuting.chen@shopee-alumni.com",
                "political_status": "共青团员",
                "target_title": "资深全栈开发工程师 / 前端技术专家",
                "target_salary": "25-30K · 15薪",
                "target_city": "深圳 / 广州",
                "job_status": "在职 - 1个月内到岗"
            },
            "summary": [
                "5年大型跨国电商平台核心前端及全栈架构经验，精通 Next.js 14 服务端渲染 (SSR) 与静态站点生成 (SSG)；",
                "深入掌握东南亚及欧美等海外复杂弱网环境下的前端性能极致调优，熟练掌控 Core Web Vitals 核心指标优化；",
                "精通 TypeScript 高阶类型编程、大型 monorepo 组件库构建及自动化测试覆盖；",
                "华南理工大学（985重点）统招软件工程学士，技术敏锐度高，代码风格严谨。"
            ],
            "work_experience": [
                {
                    "company": "Shopee (虾皮信息科技有限公司)",
                    "department": "跨境电商核心交易与买家端研发部",
                    "title": "资深全栈研发工程师",
                    "period": "2021.08 - 至今 (近3.5年)",
                    "responsibilities": "负责东南亚7大站点电商商品详情页、结算交易链路的前端架构演进与全栈开发；主导基于 Next.js 的全新微服务化重构与跨国弱网性能攻关。",
                    "achievements": "带领小组完成商品详情页向 Next.js RSC (React Server Components) 的架构迁移，首屏加载时间从 3.2s 骤降至 1.1s；在网络丢包率 15% 的极端环境下，转化率提升 4.8%。"
                },
                {
                    "company": "广州网易互动娱乐有限公司",
                    "department": "游戏官网与社区运营技术中心",
                    "title": "前端开发工程师",
                    "period": "2019.07 - 2021.07 (2年)",
                    "responsibilities": "负责多款千万级DAU旗舰游戏全球官网、赛事活动页面及玩家社区 Web 端研发。",
                    "achievements": "自研轻量级高帧率动效骨骼动画渲染模块，页面包体积精简 40%，被多个核心项目组采纳为通用基建。"
                }
            ],
            "project_experience": [
                {
                    "name": "Shopee 东南亚多语种大促核心交易站 Next.js 边缘渲染架构",
                    "role": "技术负责人",
                    "period": "2022.06 - 2024.08",
                    "tech_stack": "Next.js, React, TypeScript, Node.js, Redis, Cloudflare Workers",
                    "background": "海外节点分布广泛、用户设备性能参差不齐、多语言与多币种实时切换逻辑复杂。",
                    "solutions": "构建 Next.js 边缘同构渲染体系（Edge SSR），结合 Redis 缓存热门商品页面片段；实现图片自适应 WebP/AVIF 边缘压缩；引入流式渲染与 Suspense 骨架屏秒开体验。",
                    "metrics": "支撑双十一大促单日过亿级浏览量，LCP（最大内容渲染）优化至 1.2 秒内，全站核心 Web 指标合格率达到 97%。"
                }
            ],
            "educations": [
                {
                    "school": "华南理工大学",
                    "degree": "本科学士",
                    "major": "软件工程",
                    "period": "2015.09 - 2019.06",
                    "tier": "985 / 211 / 双一流 / 统招全日制",
                    "honors": "校优秀毕业生、多次荣获学业一等奖学金"
                }
            ],
            "skills_matrix": [
                {"category": "核心技术", "skills": ["TypeScript", "React 18", "Next.js", "Node.js", "TailwindCSS", "GraphQL"]},
                {"category": "性能调优", "skills": ["Core Web Vitals (FCP/LCP/CLS)", "边缘渲染 Edge SSR", "资源按需加载与Tree-shaking", "多语言/国际化 (i18n)"]}
            ],
            "certificates": [
                "英语专业八级 / CET-6 (625分，能以英语作为日常工作主语言)",
                "AWS Certified Solutions Architect – Associate"
            ]
        }
    },
    {
        "id": "preset-003",
        "name": "赵晨浩",
        "job_id": "fe-fullstack",
        "age": 29,
        "experience_years": 6,
        "education": "bachelor",
        "school": "电子科技大学",
        "school_tier": "985",
        "ai_score": 76,
        "ai_tier": "B",
        "state": "review",
        "salary_expect": "26-32K·15薪",
        "current_company": "美团点评",
        "current_title": "跨端移动研发专家",
        "skills": ["Flutter", "C++", "React", "跨端容器", "Android", "TypeScript"],
        "verified": False,
        "tags": [
            "✓ 6年经验·985电子科大",
            "△ 技能侧重跨端Flutter/C++",
            "△ Node.js全栈服务端经验相对薄弱",
        ],
        "radar": {
            "技术深度": 80,
            "项目规模": 78,
            "技术栈匹配": 70,
            "学历背景": 90,
            "发展潜力": 75,
        },
        "status": "employed",
        "available_time": "1个月以上/需协商",
        "apply_time": "2026-03-03 09:20",
        "ai_label": "B级·待人工复核",
        "ai_reason": "候选人985本科背景，6年美团研发经验，工程基本功扎实。但近几年主要精力聚焦于Flutter/C++跨端容器及性能调优，React有实战经验但缺少Node.js全栈架构深度，建议业务部门人工评估是否匹配当前团队需求。",
        "interview_questions": [
            "从Flutter底层渲染管线（Skia/Impeller）与Web DOM渲染机制对比，谈谈你对跨平台渲染性能极限的思考。",
            "本岗位要求Node.js全栈架构，请阐述你过往在服务端研发、数据库设计或BFF层架构方面的经验积累。",
            "如果在React和跨端原生容器之间建立高性能双向通信桥接，你会如何设计以降低通信延迟与序列化开销？",
        ],
        "full_resume": {
            "basic_info": {
                "name": "赵晨浩",
                "gender": "男",
                "age": 29,
                "work_years": 6,
                "city": "四川 · 成都",
                "phone": "137-0033-6666",
                "email": "chenghao.zhao@meituan-alumni.com",
                "political_status": "群众",
                "target_title": "移动/跨端技术专家 / 前端工程师",
                "target_salary": "26-32K · 15薪",
                "target_city": "深圳 / 成都",
                "job_status": "在职 - 考虑合适新机会 (1个月内)"
            },
            "summary": [
                "6年一线大厂跨端底座及高性能渲染引擎架构经验，精通 Flutter、C++、React Native 与混合应用；",
                "主导过美团外卖骑手端与商家端复杂跨端业务架构，对跨端容器通信（Bridge/JSI）与内存泄露治理有深厚积淀；",
                "熟练掌握 React 与 TypeScript，但近几年偏向客户端容器研发，Node.js 服务端生产经验相对较少；",
                "985 电子科技大学统招全日制本科毕业，思维敏捷，工程排障能力强。"
            ],
            "work_experience": [
                {
                    "company": "美团点评",
                    "department": "核心本地商业 · 骑手与即时配送平台部",
                    "title": "跨端移动研发专家",
                    "period": "2020.04 - 至今 (近5年)",
                    "responsibilities": "负责美团骑手端跨平台地图、订单状态机流转与动态混合容器核心技术演进；主导跨端渲染管线性能瓶颈攻坚。",
                    "achievements": "主导骑手端地图与派单模块向跨端架构迁移，双端代码复用率达 85%；通过 C++ 编写底层高性能数据序列化组件，跨端通信耗时降低 75%。"
                },
                {
                    "company": "上海哔哩哔哩科技有限公司 (Bilibili)",
                    "department": "移动客户端研发部",
                    "title": "移动端/前端研发工程师",
                    "period": "2018.07 - 2020.03 (近2年)",
                    "responsibilities": "参与 B站客户端动态流与活动页面开发，负责 React Native 混合页面的流畅度调优。",
                    "achievements": "优化长列表图片渲染与预加载，内存抖动率减少 30%。"
                }
            ],
            "project_experience": [
                {
                    "name": "美团骑手端跨平台高保真地图与派单渲染引擎",
                    "role": "核心研发",
                    "period": "2021.05 - 2023.10",
                    "tech_stack": "Flutter, C++, Dart, React, Android NDK",
                    "background": "不同手机机型跨端性能差异大，强日光下地图高刷新率发热严重。",
                    "solutions": "通过 C++ 原生接管部分复杂图层合成，设计动态降帧与内存回收策略；优化多线程状态机。",
                    "metrics": "单次配送全流程崩溃率下降至 0.01%，极端低端机型帧率稳定在 50FPS+。"
                }
            ],
            "educations": [
                {
                    "school": "电子科技大学",
                    "degree": "本科学士",
                    "major": "计算机应用技术",
                    "period": "2014.09 - 2018.06",
                    "tier": "985 / 211 / 双一流 / 统招全日制",
                    "honors": "校优秀毕业生、电子设计竞赛二等奖"
                }
            ],
            "skills_matrix": [
                {"category": "移动跨端", "skills": ["Flutter / Dart", "C++", "React Native", "Android Java/Kotlin"]},
                {"category": "前端技术", "skills": ["React", "TypeScript", "JavaScript", "HTML/CSS"]}
            ],
            "certificates": ["大学英语六级 (CET-6)"]
        }
    },
    {
        "id": "preset-004",
        "name": "张铭",
        "job_id": "fe-fullstack",
        "age": 23,
        "experience_years": 1,
        "education": "associate",
        "school": "某市职业技术学院",
        "school_tier": "other",
        "ai_score": 45,
        "ai_tier": "D",
        "state": "rejected",
        "salary_expect": "9-12K",
        "current_company": "本地初创网络科技公司",
        "current_title": "初级前端开发",
        "skills": ["HTML5", "CSS3", "JavaScript", "Vue 2", "jQuery"],
        "verified": False,
        "tags": [
            "✗ 工作年限不足(1年 < 5年)",
            "✗ 学历未达标(大专 < 本科)",
            "✗ 缺少React/TypeScript/Node.js核心技术栈",
        ],
        "radar": {
            "技术深度": 45,
            "项目规模": 40,
            "技术栈匹配": 40,
            "学历背景": 50,
            "发展潜力": 55,
        },
        "status": "available",
        "available_time": "随时到岗",
        "apply_time": "2026-03-04 16:40",
        "ai_label": "D级·硬性条件不符",
        "ai_reason": "候选人仅1年工作年限（岗位要求5年），大专学历（岗位要求本科），核心技能栈偏基础Vue与切图，缺少React/TypeScript/Node.js全栈工程能力，未通过硬性筛选门槛。",
        "interview_questions": [],
        "full_resume": {
            "basic_info": {
                "name": "张铭",
                "gender": "男",
                "age": 23,
                "work_years": 1,
                "city": "本地",
                "phone": "135-0044-5555",
                "email": "zhangming_dev@163.com",
                "political_status": "群众",
                "target_title": "前端开发助理 / 初级前端",
                "target_salary": "9-12K",
                "target_city": "深圳",
                "job_status": "离职 - 随时到岗"
            },
            "summary": [
                "1年Web前端开发基础经验，掌握 HTML5、CSS3 与基础 JavaScript/ES6 语法；",
                "熟悉 Vue 2 + ElementUI 快速搭建后台管理系统页面；",
                "能够根据 UI 设计稿完成静态页面切图与常用响应式适配；",
                "热爱编程，学习意愿强，希望在团队中进一步精进全栈开发与工程化技能。"
            ],
            "work_experience": [
                {
                    "company": "某本地初创网络科技有限公司",
                    "department": "技术开发组",
                    "title": "初级前端开发",
                    "period": "2025.03 - 2026.02 (1年)",
                    "responsibilities": "负责中小型企业展示官网切图、简易活动落地页制作以及内部简易 OA 表单页面的开发与维护。",
                    "achievements": "按时交付 8 个企业展示官网，完成日常页面样式调整与常规浏览器兼容性排查。"
                }
            ],
            "project_experience": [
                {
                    "name": "本地商贸公司企业门户与商城展示系统",
                    "role": "前端制作",
                    "period": "2025.08 - 2025.11",
                    "tech_stack": "HTML5, CSS3, Vue 2, ElementUI, Axios",
                    "background": "客户需要一套多端适配的企业宣传展示与产品目录浏览网站。",
                    "solutions": "采用 Vue CLI 快速搭建单页面，运用 ElementUI 表格与表单组件完成商品增删改查页面；使用媒体查询适配移动端。"
                }
            ],
            "educations": [
                {
                    "school": "某市职业技术学院",
                    "degree": "专科",
                    "major": "计算机信息管理",
                    "period": "2021.09 - 2024.06",
                    "tier": "高职高专 / 普通专科",
                    "honors": "校优秀学员"
                }
            ],
            "skills_matrix": [
                {"category": "基础技术", "skills": ["HTML5 / CSS3", "JavaScript", "Vue 2", "Element UI", "Git"]}
            ],
            "certificates": ["全国计算机等级考试二级 (C语言)"]
        }
    },
]

def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """根据 job_id 查找预设岗位"""
    for job in PRESET_JOBS:
        if job["id"] == job_id:
            return job
    return None

def get_candidates_for_job(job_id: str) -> List[Dict[str, Any]]:
    """根据 job_id 筛选属于该岗位的预设候选人"""
    return [c for c in PRESET_CANDIDATES if c.get("job_id") == job_id]
