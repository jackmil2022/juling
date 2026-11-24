# juling（剧灵桌面版）

AI 视频创作工作台。桌面 APP 统一启动界面与本地服务，关闭窗口后自动停止服务。

## 构建与使用

支持 Windows x64。首次构建需要 Python 3.12 或更新版本、Node.js 24.12 或更新版本、uv 和 pnpm。

在项目目录运行：

```powershell
.\desktop\build.ps1
```

构建完成后，双击桌面的 剧灵 快捷方式，或运行 `desktop/dist/剧灵.exe`。日常使用无需终端或浏览器。

这是依赖项目目录的桌面启动器，不是独立安装包。请保留 `.venv/`、`frontend/node_modules/`、`frontend/dist/` 和项目源文件。更新代码后重新构建；构建前先关闭 剧灵。

## 数据与配置

默认数据目录为 `projects/`；通过 `JULING_DATA_DIR` 可以指定其他位置。保留已有数据、`.env` 和凭据文件。模型与供应商在 APP 中配置。

本地服务仅监听 `127.0.0.1` 的动态端口，桌面启动时关闭登录认证。启动日志位于 `projects/runtime/desktop.log`。

## 开发

```powershell
pnpm --dir frontend dev
```

此命令同样打开桌面 APP，并管理前端开发服务与后端。生产构建使用 `desktop/build.ps1`。

第三方组件声明见 `LICENSES/` 及各组件目录中的许可证文件。
