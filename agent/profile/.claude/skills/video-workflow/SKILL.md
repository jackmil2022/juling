---
name: video-workflow
description: 编排视频项目。广告、带货视频或短片项目在做视频、继续项目或查看进度时必须使用；小说转短视频项目在做视频、新建或继续项目、查看进度、从头开始、拆集或自动跑完全流程时必须使用。视频项目语境中的「继续」「下一步」也触发；只生成或重做单个资产时改用对应技能。
---

# 视频工作流

执行前，用 Read 读取项目内的操作正文 `.claude/skills/video-workflow/references/workflow.md`。

正文引用其他技能的章节时，先读该技能入口；入口仅为索引时，再读它指向的正文。

源目录中该正文按 `content_mode` 分为 `references/workflow.ad.md`、`references/workflow.drama.md`、`references/workflow.narration.md`；同步到项目时只部署当前模式的一份，文件名为 `workflow.md`。
