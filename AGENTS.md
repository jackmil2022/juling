# 剧灵

本仓面向 Windows 桌面使用。保持启动入口集中在 `desktop/`，不要恢复独立 Web 启动器、CI、测试套件或文档站。

## 结构

- `frontend/`：React 界面，使用 pnpm。
- `backend/`：FastAPI、核心功能、uv workspace 子包和数据库迁移。
- `agent/profile/`：创作 Agent 的运行配置、技能和角色提示词。
- `desktop/`：Electron 窗口、子进程生命周期与 Windows 启动器构建。
- `projects/`、`public/`、`third_party/`、`LICENSES/`：用户数据、应用资源、第三方组件和许可证，保持路径稳定。

## 验证

构建入口为 `desktop/build.ps1`。前端修改运行 `pnpm --dir frontend build`；后端修改检查 Python 语法、生产模块导入与 Alembic 迁移发现；桌面生命周期修改应实际确认窗口加载和关闭后服务退出。测试代码已按用户要求移除，不要重新生成测试文件。

## 保留边界

保留用户数据、`.env`、凭据、数据库迁移、运行时提示词及第三方声明。供应商端点的连接测试是产品功能，不属于已删除的自动化测试。依赖变更同时更新对应锁文件。使用中文简洁回复，不创建重复脚本或无用文档。
