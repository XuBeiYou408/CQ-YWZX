---
name: enterprise-kb-query
description: 公司内部制度查询（年假/考勤/请假/报销/差旅/福利/保密/专利/员工手册等）。凡用户询问公司内部制度、规定、流程，必须先用本技能路由到企业知识库 MCP 工具检索，禁止用网络搜索回答公司内部问题。
---

# 企业制度查询路由

## ⚠️ 关键：MCP 工具必须用 DeferExecuteTool 调用，参数是「两层平级」结构

`toolName`（工具全名）与 `params`（工具自己的参数）是**平级的两个顶层字段**：
`toolName` 放**最外层**，工具参数放 `params` 里面。

✅ **正确写法（照抄这个形状，不要自己改结构）**：

```json
{
  "toolName": "mcp__enterprise-knowledge-base__search_knowledge_base",
  "params": { "query": "年假制度 天数规定", "top_k": 3 }
}
```

❌ **以下写法必然失败**（返回 `Error: "toolName" is required. Provide the exact tool name as returned by ToolSearch.`）：

```json
{ "params": { "query": "...", "toolName": "mcp__enterprise-knowledge-base__search_knowledge_base" } }   ← toolName 被塞进了 params 内部
{ "params": { "params": { "query": "..." } } }                                                          ← params 套了两层
```

> 口诀：**toolName 和 params 是兄弟，不是父子**。不要把 toolName 放进 params 里面。
> 失败时**不要**反复重试同一形状——先检查 toolName 是否写在了最外层。

## 执行步骤

用户询问公司内部信息时，严格按以下步骤执行：

1. **调用 ToolSearch**，用 `tool_names: ["mcp__enterprise-knowledge-base__search_knowledge_base"]` 加载知识库检索工具。
2. **按上面的结构调用 `DeferExecuteTool`**：`toolName` 填 `mcp__enterprise-knowledge-base__search_knowledge_base`，`params` 填 `{"query": "自然语言问题（如 年假制度 天数规定）", "top_k": 3}`。
3. **基于返回的文档片段回答**，并注明来源文件名。
4. 检索无结果时，如实告知"知识库中未找到"，可再调用 `mcp__enterprise-knowledge-base__list_knowledge_documents` 列出已收录文档供用户确认。

## 禁止事项

- **禁止用 WebSearch / 网页搜索回答公司内部制度问题**——互联网上的"年假 5/10/15 天"是《职工带薪年休假条例》的法定下限，公司实际制度以内部知识库文档为准，两者可能不同。
- 禁止在未调用知识库工具的情况下凭模型自身知识编造公司制度。

## 触发词（满足任一即走本流程）

年假、带薪年休假、休假、请假、考勤、打卡、报销、差旅、福利、入职、离职、试用期、加班、工资、社保、保密、数据安全、专利、知识产权、公司制度、公司规定、内部流程、员工手册、企业知识库
