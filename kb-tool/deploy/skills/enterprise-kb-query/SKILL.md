---
name: enterprise-kb-query
description: 公司内部制度查询（年假/考勤/报销/福利/保密/专利/员工手册等）。必须先调用知识库工具检索才能作答，禁止凭记忆作答或编造文档名/ID。
---

# 企业制度查询（先检索再答）

**问公司制度 → 必须先真正检索，禁止凭自己记忆作答或编造文档名/Knowledge ID。**

1. `ToolSearch`：`{"tool_names": ["mcp__enterprise-knowledge-base__search_knowledge_base"]}`
2. `DeferExecuteTool`：

```json
{"toolName": "mcp__enterprise-knowledge-base__search_knowledge_base", "params": {"query": "用户的问题", "top_k": 3}}
```

- toolName 与 params **平级**（兄弟，不是父子）。
- 依据返回内容作答，注明来源文件名。
- 无结果或调用失败 → 如实说"知识库中未找到"，不要编答案。
