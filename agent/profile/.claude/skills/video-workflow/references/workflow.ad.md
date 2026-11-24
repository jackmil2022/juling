<!-- mode: ad -->

# 广告/短片工作流

广告或短片（`ad`）只做单集单视频，剧本固定为 `scripts/episode_1.json`，按 `target_duration` 规划镜头。不规划分集、不拆分、不处理小说源文件。

## 工作流步骤

先调用 `mcp__juling__get_workflow_plan({})`，每次动作完成后刷新。阶段判断只看 `steps[]`、`blockers`、`status.operations` 与 `next_action`；`plan.status` 已含 `project` / `target` / `content` / `issues` / `gates` / `artifacts`。Read 只补充创作输入与商品 soft gate 信息。

- `blockers` 非空：展示并停止变更。
- `next_action.type == "none"` 且无 `blockers`：若 `steps` 中 `edit` 为 `completed`，工作流已完成；否则告知用户 `status.issues`。
- 「继续」：按 `next_action` 推进；`next_alternatives` 非空时列出选项，由用户选择。
- 点名操作：`status.operations` 中为 `admitted` 或未列出就执行；为 `refused` 则转述 `reason`（如 `ad_brief_and_products_missing`：创作灵感与商品都没填）。

适用步骤看 `plan.steps[].required`，不另列各生成模式的步骤表。字段、受控动作表、旁白交付、整批准入、四条状态轴及 stale 与历史规则见 [工作流计划](../../../references/workflow-plan.md)。

按 `next_action.type` 直接进入对应步骤：

- `next_action.type == "collect_project_input"` → 步骤 2
- `next_action.type == "generate_script"` → 步骤 4「一键生成剧本」
- `next_action.type == "start_blank_script"` / `"add_script_items"` → 引导用户在 Web 端手写或补条目（见 workflow-plan 参考）
- `next_action.type == "generate_asset_sheets"` → 步骤 5「资产图」
- `next_action.type == "repair_video_units"` → 步骤 7 的视频单元修复
- `next_action.type == "generate_storyboards"` → 步骤 7 的 storyboard 单图路径
- `next_action.type == "confirm_request_duration"` → 步骤 7 的申请档位确认
- `next_action.type == "generate_videos"` → 步骤 7 的视频生成
- `next_action.type == "create_edit_timeline"` → 步骤 8

调用工具或 dispatch 子智能体时带入 `target.episode`、`next_action.args` 与 `requested_ids`，不二次检查 `generation_mode` 来改选阶段。广告和短片不支持宫格装配。步骤内的商品原图与 sheet 过目规则是执行动作前的 soft gate。

1. **确认项目状态**：按计划确认 `content_mode=ad` 与项目级 `generation_mode`；Read `project.json` 补充 `title`、`target_duration`、`brief` 与 `products`。生成模式创建后不可更改。
2. **创作输入**：带货项目未登记商品或缺原图时，引导用户在 WebUI 上传；原图是保真锚点。用 `mcp__juling__patch_project` 写商品描述、品牌与 `brief`。通用短片不索要商品。
3. **起草卖点**：卖点不挡脚本生成。`status.content.products_without_selling_points` 非空时可向用户提议起草；用户同意或主动要求时，根据 brief、描述与原图起草，与用户确认后用 `patch_project` 写回。
4. **一键生成剧本**：`brief` 与商品至少一项后，调用 `mcp__juling__generate_episode_script({"episode_id": target.episode})`。广告不走 script_plan，结果直接成为正式脚本；参考图生视频直接产出 `shots[]`，参考生视频直接产出自包含 `video_units[]`。剧本引用的新角色、场景、道具随之登记为待生成资产，回执列出它们。总时长偏离 `target_duration` 时提醒用户，不阻塞保存。用户要整份重做时传 `regenerate: true`，丢失清单的确认与违约失败的处理见 generate-script skill。
5. **资产图**：调用 `mcp__juling__generate_assets({"episode_id": <next_action.args.episode_id>})`：服务端生成本集引用、仍缺资产图的全部资产（含商品、衍生与剧本生成时新登记的资产），与 Web 集层同一份名单。生成完成后按 [generate-assets](../../generate-assets/SKILL.md) 的「审核检查点：审图」派发 `review-images` 审图，把审图报告交给用户确认。
6. **sheet 过目（软门禁）**：商品有 `product_sheet` 时，请用户在首次分镜或参考生视频生成前确认它与真品一致；只有原图时直接继续。
7. **编排与生成**：

   - `repair_video_units`：调用 `mcp__juling__get_episode_script({"script": target.script_filename})` 读取正文与 revision，只处理 `requested_ids` 对应的视频单元；再用一次 `mcp__juling__patch_episode_script({"script": target.script_filename, "base_revision": revision, "operations": [{"op": "update", "id": unit_id, "fields": {"text": "...", "duration_seconds": ...}}]})` 写回全部视频单元的完整规划（每个视频单元一条有序 update）；由工具重算 `needs_replan`，不要直接编辑标记。每个视频单元保持单一发声归属，商品/角色/场景/道具都用 `@[名称]`。修复后立即用 `generate_videos` 的 `selected` scope 与 `force: true` 点名重做这些视频单元，再刷新状态。
   - `next_action.type == "generate_storyboards"` → 调
     `mcp__juling__generate_storyboards({"script": target.script_filename, "segment_ids": requested_ids})`
   - 参考图写入后，按 [generate-storyboard](../../generate-storyboard/SKILL.md) 的「审核检查点：审图」派发 `review-images` 审图，把审图报告交给用户确认
   - `next_action.type == "confirm_request_duration"` → 按 `admission.confirmation.tiers[]` 逐档位展示
     涉及的视频单元与费用，确认后经 `confirmed_request_durations` 带回下一次 `mcp__juling__get_workflow_plan`
   - `next_action.type == "generate_videos"` → 先看 `plan.steps[].admission.decision`：只有 `admitted`
     才入队，`blocked` / `confirmation_required` 时**一个任务都不入队**，逐视频单元报告 `unit_id`、
     `problems[].code`、原因与 `problems[].action`（被 `blocked_unit_ids` 连累的视频单元带
     `generation_batch_admission_withheld`，如实说明不是它自身有问题）；修掉被拒视频单元后整批重来，
     不拆批先跑通过的那一半。入队时若 `requested_ids` 非空则调
     `mcp__juling__generate_videos({"script": target.script_filename, "target": {"scope": "selected", "ids": requested_ids}, "force": true})`；
     `requested_ids` 为空时才调 `mcp__juling__generate_videos({"script": target.script_filename, "target": {"scope": "episode", "episode_id": target.episode}})`。
     返回后按逐 ID 分账陈述结果（`succeeded` / `failed` / `blocked` / `skipped`），并把 workflow 步骤
     状态、队列任务、供应商 checkpoint、产物时效四轴分开说——「任务成功」不等于「当前产物有效」；
     stale 产物照常可用，是否重做由用户决定，不自动删除或重生已付费产物
   - 带货项目走参考图生视频时，先审核商品分镜保真度，再产生视频费用；通用短片没有商品分镜，不设这道审核。
   - 分镜路线遇到 `storyboard_video_*` 阻断，按 `generate-video` skill 让 Agent 逐镜做图生图融合、补齐说话人音色；超时或融合后仍超槽位则拆分镜，修复后重新读取计划。
   - 参考生视频按自包含视频单元生成，跳过分镜；参考图在执行期按正文 `@[名称]` 的首次提及顺序解析，商品与角色、场景、道具同规则。用户不满意时按 `unit_id` 点名重做。

8. **剪辑**：TTS 配音项目（`plan.status.artifacts.audio.missing_ids` 非空）先按 `generate-narration-audio` skill
   调 `mcp__juling__generate_narration_audio({"script": target.script_filename})` 补齐缺失的旁白配音，不带
   `segment_ids`；项目选择 TTS 即已授权。剪辑时间线一建好这一步就完成，之后工作流不会再回到这里补配音。
   再调 `mcp__juling__create_timeline({"from": "script", "episode": target.episode, "name": "完整版"})`
   按脚本机械新建一条剪辑时间线，至少有一条剪辑时间线，这一步即完成。之后按 `edit-video` skill
   在它上面剪辑，只在用户要求时出成片或导出剪映草稿。声音归属与字幕时序由服务端 presentation 结果决定——
   **不要自行估算字幕时间轴，也不要替用户判断 TTS 是否必需**。stale 产物照常可用，出片不清空也不
   覆盖旧付费媒体。

## 通用短片（无商品）

`products` 为空即通用短片。跳过商品上传、卖点与 product sheet；把 `brief` 补充到足以表达主题、情绪、画面风格与节奏。角色、场景、道具资产照常可用。

## 镜头时长约束

参考图生视频的分镜时长取该路线可用的模型档位，以剧本 schema 校验为准。用 `mcp__juling__get_video_capabilities` 查询模型声明的 `supported_durations` 和当前条件下的 `duration_constraints.allowed`。参考生视频的视频单元使用剧本模型允许的正整数编排时长，生成预检再投影到供应商档位。发现非法值时先用 `patch_episode_script` 修正。

## 边界

- storyboard 广告以 `shots[]` 为唯一真相源；reference 广告以自包含 `video_units[]` 为唯一真相源。
- 参考生视频的视频单元自持引用语法正文、编排时长、生成资产与规划状态；编辑这些字段后刷新计划。
- 视频单元改序与字段修复使用 `patch_episode_script`，视频生成使用 `generate-video` skill。
