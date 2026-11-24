# 剧灵 外部 Agent 接入任务

你正在帮助用户把当前 Agent 宿主连接到 剧灵。完成以下步骤后再结束任务；项目创作流程由安装后的 skill 与 MCP 工具说明提供。

## 1. 获取接入信息

让用户打开 [剧灵 设置页的「访问令牌」]({{BASE_URL}}/app/settings?section=access-tokens)，创建访问令牌。完整令牌只显示一次；用户可以把它提供给其明确选择的当前 Agent。

MCP 端点：

```text
{{BASE_URL}}/mcp
```

## 2. 执行接线

由 Agent 配置 MCP 端点与 Bearer 访问令牌，调用 `list_projects` 验证连通。后续任务由 Agent 负责思考与编排，MCP 只提供具体操作。

## 3. 完成判据

`list_projects` 调用成功并返回结构化 `projects` 列表，且宿主 MCP 与工作区配置指向同一连接时即完成；空列表也是成功。
