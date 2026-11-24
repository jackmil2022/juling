# 技能总索引

本文件只用于导航，不是可调用技能。按任务选择入口，再读取入口指向的操作正文。

| 分类 | 技能入口 |
|---|---|
| 项目编排 | [视频项目工作流](video-workflow/SKILL.md) |
| 项目管理 | [项目设置与资产登记](manage-project/SKILL.md)（内部） |
| 剧本 | [正式脚本提示词](generate-script/SKILL.md)（内部） |
| 素材生成 | [资产图](generate-assets/SKILL.md)、[分镜参考图](generate-storyboard/SKILL.md)、[视频](generate-video/SKILL.md)、[旁白配音](generate-narration-audio/SKILL.md) |
| 素材生成 | [宫格参考图](generate-grid/SKILL.md)（仅 narration / drama 的 `storyboard`，且 `grid_storyboard=true`） |
| 剪辑交付 | [剪辑视频](edit-video/SKILL.md) |
| 供应商接入 | [自定义调用端点](adapt-custom-endpoint/SKILL.md) |

内置技能的 `SKILL.md` 只保存调用元数据与阅读入口；本技能操作规则放在其 `references/`，跨技能约定放在[共享参考](../references/)，工具脚本留在对应技能的 `scripts/`。项目自定义入口若仍有正文，以该正文为准。
