# 生成参考图

通过生成队列创建参考图，画面比例根据 content_mode 自动设置。

片头首镜必选一张构图参考图，说明场景、人物和物件的空间关系。只为正式脚本中 `reference_image_ranges` 选出的时间段生成参考图。后续分镜的空数组表示无需出图，直接进入视频生成；未选中的时间段不补写图片提示词，也不补图。旧剧本未选片头参考图时，可经用户授权覆盖片头提示词，不要把每个时间段都视为需要生成。

> 生成模式规格详见 `.claude/references/generation-modes.md`。

## 工具调用

**重要：生成参考图必须调用下列 MCP 工具入队。此 skill 不提供任何 Python/Shell 脚本，不得用 BASH 调 `python .../scripts/*.py`。**

通过 MCP 工具入队：

| 操作 | 工具 |
|------|------|
| 提交所有缺失参考图 | `mcp__juling__generate_storyboards({"script": "episode_1.json"})` |
| 重新生成指定 ID | `mcp__juling__generate_storyboards({"script": "episode_1.json", "segment_ids": ["E1S05"]})` |
| 重新生成多个 ID | `mcp__juling__generate_storyboards({"script": "episode_1.json", "segment_ids": ["E1S01", "E1S02"]})` |

> **选择规则**：`segment_ids` 兼容 narration 的 segment_id 与 drama 的 scene_id；未传则提交所有缺失项。
>
> **依赖**：generation worker 必须在线（图像/视频两条独立通道），worker 负责实际生成与速率控制。

## 工作流程

1. **加载项目和剧本** — 确认所有角色都有 `character_sheet` 图像
2. **生成参考图** — MCP 工具自动检测 content_mode，按相邻关系串联依赖任务
3. **审核检查点** — 按「审核检查点：审图」派审图子智能体看图，把报告与重新生成建议交给用户确认；用户可批准、要求重新生成，或要求编辑
4. **更新剧本** — 更新 `storyboard_image` 路径和场景状态

## 审核检查点：审图

参考图生成完成后，先由只读的审图子智能体 `review-images` 看图，再把结论交给用户确认。审图不会触发生成或编辑，不产生生成费用；子智能体看图的模型调用照常计入 Agent 会话用量。宫格项目在切分落格、写入参考图之后再审。

1. **派发**：由主 Agent 派发（子智能体不能再派子智能体：本 skill 在生成子智能体里执行时，生成结果交回主 Agent 后由主 Agent 派发）。只派本轮生成成功的分镜，按相邻分镜分组，每组至多 20 张；有多组时在同一条消息里为每组各发起一次 `review-images` 调用，让各组并行。派发消息写明图片类型 `storyboard`、剧本文件（如 `scripts/episode_1.json`）、本组分镜 ID 和用户的关注点。
2. **交给用户**：把各组报告汇总给用户：哪些可用，哪些建议重新生成或编辑、原因是什么，哪些存疑。称呼分镜用它在本集的位置（如「分镜 5」），不说分镜 ID。有建议重新生成、编辑或存疑的分镜时，用 AskUserQuestion 多选（`multiSelect: true`）请用户勾选要处理的分镜，每个选项写明位置、原因与建议的处理方式。用户确认前不重新生成，也不编辑。
3. **执行**：按用户勾选的分镜与下一节「编辑 vs 重新生成」处理，调工具时用分镜 ID。处理完成后，可以对新版本再派一次 `review-images` 验收。

用户追问某几张参考图时，用 `mcp__juling__inspect_images` 直接看图回答，不必派发子智能体。

## 审核检查点：编辑 vs 重新生成

- **只想改局部**（如某个分镜的手部畸形、背景杂物、光线偏差），且构图/角色一致性满意 →
  用 `mcp__juling__edit_images({"resource_type": "storyboard", "script_file": "episode_1.json", "edits": [{"id": "E1S05", "instruction": "去掉背景里多余的路人"}]})`
  保底图微调，不影响 `image_prompt`，一次可批量下发多个分镜
- **想推翻构图或角色/参考图关系**，或 `image_prompt` 本身要改 → 用
  `patch_episode_script` 改 `image_prompt` 后，紧接着调 `generate_storyboards` 重新生成
- 编辑不会更新 `image_prompt`——编辑后再触发 `generate_storyboards` 仍按原 `image_prompt`
  重画，编辑效果只能从版本历史找回

## 角色一致性机制

MCP 工具自动处理以下参考图传入，无需手动指定：
- **character_sheet**：场景中出场角色的资产图，保持外貌一致
- **scene_sheet / prop_sheet**：场景中出现的场景 / 道具资产图
- **商品参考（广告/短片项目）**：分镜 `products_in_shot` 非空时，每件商品只注入一张 `product_sheet`，排在其他参考之前，不上传实拍图。正文说明商品的位置、朝向、相对大小、露出程度及与人物的关系。
- **上一张参考图**：相邻片段默认引用，排在参考图列表最后，只参考构图与色调
- 当片段标记 `segment_break=true` 时，不引用上一镜的参考图

参考图对模型只是一个按顺序排列的图数组，prompt 用「图N」指认它们（N = 参考图在数组中的位置，商品在前，
然后是角色 / 场景 / 道具资产图，上一张参考图最后）：
- 生成端在 `Style` 与 `Scene` 之间插入 `Reference_Images` 清单，按实际上传槽位逐条列出「图N」、素材名称和用途。
- `image_prompt.scene` 里用 `@[登记名]` 指认资产（衍生形态写 `@[角色/衍生]`），生成端按上述编号把它换成对应的「图N」；
  该名字须同时写进条目的引用字段（`characters_in_*` / `scenes` / `props` / `products_in_shot`），参考图只由引用字段决定，`@[]` 不会额外带图
- 未登记或不在引用字段里的 `@[名称]` 按名字原样发送；`generate_episode_script` / `patch_episode_script` 的回执 `warnings` 会列出这类引用，按提示补登记或补引用字段后重新生成

## Prompt 模板

生成端按项目 style、参考图列表与条目 `image_prompt` 渲染最终 prompt（`get_prompt_preview` 可查看逐字文本）：

```
Style: [项目 style]
Reference_Images:
- 图1「林清」：角色参考图。保持面孔、发型、体态和服装一致；姿态、朝向和站位按正文。
- 图2「客厅」：场景参考图。参照空间布局、环境材质和背景地标，把人物和道具放入同一空间。
Scene: [image_prompt.scene，包含镜头、光线、氛围；@[登记名] 已换成对应的图N]
Avoid: 水印、多余文字、Logo
```

> 画面比例通过 API 参数设置，不写入 prompt。

## 生成前检查

- [ ] 所有角色都有已批准的 character_sheet 图像
- [ ] 场景视觉描述完整
- [ ] 角色动作已指定

## 错误处理

结果结构与逐 ID 问题码见 `.claude/references/generation-results.md`。

- 单场景失败不影响批次，工具返回 `requested / succeeded / failed / blocked` 的逐 ID 结果
- 按每一项自带的 `problem.code` 与 `problem.action` 决定重试还是先改输入，不要读文本猜
- 不传 `segment_ids` 即只补缺；已失效但可用的旧参考图会被复用，不自动重生
- 可重试的场景用 `mcp__juling__generate_storyboards({"script": "...", "segment_ids": [...]})` 点名重做
