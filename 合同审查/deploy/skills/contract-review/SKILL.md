---
name: contract-review
description: 合同审查。用户给出合同文件（docx/pdf/txt）时，默认执行完整审查：直接调用 review_contract_file，不要反问用户意图。
---

# 合同审查（直接执行）

**用户给出合同文件 → 立即按下面两步审查，不要反问、不要自己写结论。**

1. `ToolSearch`：`{"tool_names": ["mcp__contract-reviewer__review_contract_file"]}`
2. `DeferExecuteTool`：

```json
{"toolName": "mcp__contract-reviewer__review_contract_file", "params": {"file_path": "合同的本地绝对路径"}}
```

- toolName 与 params **平级**（兄弟，不是父子）：不要把 toolName 塞进 params 里（会报 `toolName is required`）。
- 工具自动完成：完整审查 → 生成批注版 Word + 审查报告 .md，返回摘要和路径。
- 总结**只写一条**（结论 + 风险数 + 两个文件路径），用 `present_files` 展示这两个真实文件后结束。
- 调用失败或无结果 → 如实说明，不要编造审查内容或文件名。
