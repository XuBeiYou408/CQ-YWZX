---
name: contract-review
description: 合同审查/风险扫描/红线批注/合同起草。凡用户提供合同文件（docx/pdf/txt）或要求审查合同、扫描条款风险、检索法条判例、导出批注版 Word、起草新合同，必须先用本技能路由到 contract-reviewer MCP 工具，禁止把合同当作普通文档走腾讯文档编辑技能。用户拖入或给出合同文件时，无论是否附带文字说明，默认意图就是合同审查——直接执行本技能，不要反问用户意图。
---

# 合同审查路由

## ⚠️ 关键：MCP 工具必须用 DeferExecuteTool 调用，参数是「两层平级」结构

`toolName`（工具全名）与 `params`（工具自己的参数）是**平级的两个顶层字段**：
`toolName` 放**最外层**，工具参数放 `params` 里面。

✅ **正确写法（照抄这个形状，不要自己改结构）**：

```json
{
  "toolName": "mcp__contract-reviewer__review_contract_file",
  "params": { "file_path": "C:\\Users\\ASUS\\Desktop\\合同.docx" }
}
```

❌ **以下写法必然失败**（返回 `Error: "toolName" is required. Provide the exact tool name as returned by ToolSearch.`）：

```json
{ "params": { "file_path": "...", "toolName": "mcp__contract-reviewer__review_contract_file" } }   ← toolName 被塞进了 params 内部
{ "params": { "params": { "file_path": "..." } } }                                                  ← params 套了两层
```

> 口诀：**toolName 和 params 是兄弟，不是父子**。不要把 toolName 放进 params 里面。
> 失败时**不要**反复重试同一形状——先检查 toolName 是否写在了最外层。

## 执行步骤

用户提供合同文件或表达合同相关意图时，严格按以下步骤执行：

1. **调用 ToolSearch**，用 `tool_names: ["mcp__contract-reviewer__review_contract_file"]` 加载合同审查工具。
2. **按上面的结构调用 `DeferExecuteTool`**：`toolName` 填 `mcp__contract-reviewer__review_contract_file`，`params` 填 `{"file_path": "合同的本地绝对路径"}`。该工具自动完成：完整审查 → 生成批注版 Word（原文件同目录）→ 生成审查报告 .md。**返回值仅为结果摘要 + 交付文件路径**（不含报告全文）。
3. **向用户转达摘要结论与文件路径即可**，不要尝试复述报告全文；用户需要某项细节时，用 Read 工具读取 .md 报告文件的对应部分。
4. 若用户要求单独导出批注版，再 `ToolSearch` 加载 `mcp__contract-reviewer__export_annotated_docx` 并调用。
5. 轻量快查场景可按需加载：`mcp__contract-reviewer__scan_clause_risk`（条款风险秒级扫描）、`mcp__contract-reviewer__lookup_statute`（法条检索）、`mcp__contract-reviewer__search_precedent`（判例检索）、`mcp__contract-reviewer__detect_contract_type`（合同类型识别）、`mcp__contract-reviewer__get_clause_rewrite`（改写建议）。
6. **完整审查/批注导出/起草合同报错时**，先调用 `mcp__contract-reviewer__ping` 体检环境（LM Studio 是否在线、有哪些模型），并按其输出向用户说明处理办法。

## 禁止事项

- **禁止把合同文件路由到 tencent-docs-routing / tencent-local-office-edit / tencent-docx**——那些技能只做文档读写与排版，不具备法务审查能力；用户拖入合同的目的默认是审查，不是编辑格式。**也不要先调 tencent-docs-routing"看看是什么文件"再决定——合同文件直接走本技能。**
- **禁止在拖入合同文件时反问用户想做什么**——默认动作就是合同审查（用 review_contract_file）；审查完成后可再问是否需要进一步操作。
- 禁止在未调用 contract-reviewer 工具的情况下凭模型自身知识输出合同审查结论。

## 触发词（满足任一即走本流程）

合同、合同审查、审合同、条款风险、风险扫描、红线、批注版、违约责任、保密条款、知识产权条款、法条检索、判例、起草合同、新合同、contract review
