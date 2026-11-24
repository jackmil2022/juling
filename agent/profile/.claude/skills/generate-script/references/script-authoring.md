# generate-script

Agent 直接补写既有分镜的视觉层、修复已保存的草稿。参考生视频单元、显式重写与广告整稿走下文的后端文本工具。

## Agent 补写既有分镜

适用于正式脚本包含 `segments`、`scenes` 或 `shots`，且任务仅补缺。确认集 ID、脚本文件名和用户指定范围。用 `get_workflow_plan` 核对当前状态，用 `get_episode_script` 读取正式脚本与 `revision`。

1. 用 `generate_episode_script` 的 `dry_run: true` 取得现有写作规则、待写条目、字段和输出格式。传同一 `episode_id`、范围 `entry_ids` 与用户附加指令。范围为空表示本集带待编写标记的条目；点名时只处理指定分镜。已齐则直接回报。
2. 你按返回的规则写视觉层。视频的 `action` 遵守分镜现有时长和参考图时间段。图片正文 `scene` 按顺序保留「核心意象」「媒介与笔触/质感」「色彩情绪与视觉焦点」三段；优先写主体和可验证的画面细节。沿用已定稿的原文、台词和资产，按规则返回 `reference_image_shots`。完整提交预览列出的待写条目，保留真实 ID。每条提交它的 ID、`image_prompt`、`video_prompt`、`reference_image_shots`。顶层数组及 ID 键分别为 `segments` / `segment_id`、`scenes` / `scene_id`、`shots` / `shot_id`。图片为空时用 `null`，图片正文用 `{"scene": "..."}`，视频动作正文用 `{"action": "..."}`。后端按范围忽略已有字段。
3. 调 `submit_storyboard_prompts`，传 `episode_id`、读取时的 `base_revision`、相同 `entry_ids`，以及 `visual_output`（预览要求的 `segments`、`scenes` 或 `shots` 对象）。后端只合并缺失字段。拒绝时按具体原因修正；版本冲突先重读，按新状态重新判断范围。收到成功回执后汇报 `authored_ids`，不自动提交付费生成。

## Agent 修复已保存的草稿

1. 用 `open_draft` 读取指定 `episode_id` / `doc_type` 的正文、违约和版本。界面发来 `existing_revision` 时原样传入；版本冲突即停止，请用户刷新，避免打开一个新副本。
2. 根据违约报告和附加指令修改完整 `content`，只改受影响的条目或集级字段。用 `patch_draft` 提交完整正文，`base_revision` 传读取时的草稿版本。不要重抽、丢弃草稿或直接改文件。
3. 用 `patch_draft` 回执的新版本调用 `promote_draft` 重新校验；没有正文变更时用读取版本。正式内容发生并发修改时停下说明，不自动接受新的 `formal_revision`。仍有违约就查看新报告，按其修正；无法安全处理时说明剩余问题。以工具回执为准。

## 后端文本工具的前置条件

1. 项目目录下存在 `project.json`（含 style / overview / characters / scenes / props）
2. **正式脚本 `scripts/episode_N.json` 已存在**（N 是目标集的集 ID，取自计划 `target.episode`，不是第几集）（drama / narration / reference_video）：内容确认即把脚本规划整集转为正式脚本，全部条目带待编写标记。确认有两条等价路径：用户在 Web 端点击确认，或在对话中明确同意后由主 Agent 调用 `mcp__juling__confirm_script_review({"episode_id": N})`。本工具只读正式脚本、不读脚本规划：脚本规划缺失或重跑后尚未确认都不影响编写。
   - **ad（广告/短片）**：尚无正式脚本时本工具按 `project.json` 的 `brief` + `products`（含 selling_points）+ `target_duration` 整份生成（后端按审定的带货八段框架配比表构建 prompt，`products` 为空自动分流通用短片），`brief` 与 `products` 至少一项。结果直接成为正式脚本，不经内容确认；引用里的新角色 / 场景 / 道具由模型列进 `new_assets` 并给出处理决定，随正式脚本登记为待生成资产，与已登记同类资产同名的自动归并，回执列出本次新登记的资产。已有正式脚本时与其他路线一样只编写待编写条目，整份重做见下文。
3. **约束失败产出保留为待修复草稿，不丢弃重抽**：参考生视频提示词编写的产出违反内容约束时，正式文件不写，产出连同逐条违约报告落到 `*.invalid.json`。用 `open_draft` 读取草稿及 revision，按 `violations[]` 修复完整 `content`，再用 `patch_draft` 提交；随后以相同 `episode_id` 与 `doc_type: reference_prompt_authoring` 调 `promote_draft`，仍违约则继续 open → patch → promote，无轮次上限。

## 用法

通过 MCP 工具调用（项目名由 session 绑定，不需要传）：

```text
mcp__juling__generate_episode_script({"episode_id": N})
mcp__juling__generate_episode_script({"episode_id": N, "instructions": "<附加指令原文，可选，无则省略>"})
mcp__juling__generate_episode_script({"episode_id": N, "dry_run": true})   # 仅预览 prompt
```

输出路径由工具内部固定为 `{project}/scripts/episode_{N}.json`，不支持自定义；
如需重命名或归档，请在 Web 端操作。

### 参考生视频补写与显式重写（`author_prompts`）

正式脚本里带待编写标记的条目（内容确认转换出的全部条目、手动新增的分镜 / 单元）还没有视觉层。
工作流计划的 `next_action.type` 为 `author_prompts` 时，`requested_ids` 就是这些待编写条目。
不传 `entry_ids` 调用即编写全部待编写条目，写回后标记清除：

```text
mcp__juling__generate_episode_script({"episode_id": N})
```

- **默认补缺**：图片提示词与视频提示词各自整份判断，已有的保留，只补缺失的那一份；参考生视频按待编写
  标记展开单元正文。已编写完成的条目（包括用户手写的）保持原样。
- **`entry_ids` 只划定范围**：点名条目照样补缺，视觉层已齐的跳过，回执列出跳过项。
- **`rewrite: true` 是显式重写**：重新编写范围内条目的全部视觉层，只在用户明确要求覆盖这几条时传入；内容字段
  （台词、旁白正文、对应原文）与备注、已生成产物照常保留。会覆盖已有内容时工具先返回
  `prompt_overwrite_required`，回执正文是服务端生成的丢失清单，`params.prompt_overwrite.revision` 是认可令牌：
  把清单原文转述给用户，得到同意后才以该 revision 作为 `overwrite_revision` 重新调用。
- 没有要编写的条目时工具不调用模型、不改剧本，回执会说明。整集重做走重跑脚本规划并重新确认。
- 参考生视频在调用模型前按正式脚本复判待编写单元的正文与台词量。不通过时任务失败，问题码
  `prompt_authoring_dialogue_overload`（台词念不完）或 `prompt_authoring_unit_invalid`，`action` 为 `fix_input`；
  `params.position` 是该单元在本集的位置，界面称「视频单元 N」。向用户转述原因时用这个称呼，请用户在时间线上
  修改该单元的正文或时长，不要原样重试。

### 广告/短片整份重做（`regenerate`）

用户要求重新生成整份广告脚本时传 `regenerate: true`，不需要先删正式脚本：

```text
mcp__juling__generate_episode_script({"episode_id": N, "regenerate": true, "instructions": "<可选>"})
```

- 用户在重做弹窗查看清单后点击「交给 Agent」发出的消息已包含覆盖确认和 `overwrite_revision`。将该版本原样与
  `regenerate: true` 一起传入，无需再次确认。
- 已有正式脚本且没有有效版本时，工具返回 `script_overwrite_required` 与丢失清单（将移除的条目与名下的参考图、
  视频等）。缺少确认时，先转述清单原文并取得用户认可，再传 `params.script_overwrite.revision`；若原先确认的
  版本已失效，停止并说明冲突，不能用旧授权自动换成新版本重试。
- 上一次登记的资产在重做后保留，即使新脚本不再引用。
- 整份生成的产出违约（引用了未登记也未列进 `new_assets` 的名字、处理决定解析不出、结构不合）时任务失败，
  问题码 `ad_script_rejected`，正式脚本、资产与草稿都不变。把失败原因转述给用户，按原因补一句附加指令再生成。

**通过本技能所列 MCP 工具提交和验收。不得用 Bash 或直接改剧本文件。**

## 生成流程

MCP 工具内部通过 `ScriptGenerator` 完成以下步骤：

1. **加载 project.json** — 读取 content_mode、characters、scenes、props、overview、style
2. **加载正式脚本** — 在范围内（全部待编写条目，或 `entry_ids` 点名的条目）按补缺或显式重写选出本次编写的条目与字段；ad 尚无正式脚本或 `regenerate` 时整份生成
3. **构建 Prompt** — 由 `lib.prompts.prompt_builders_script`、`lib.prompts.prompt_builders_reference` 或 `lib.prompts.prompt_builders_ad` 生成，输入是这些条目的内容字段
4. **调用 TextBackend** — 由 `TextGenerator` 按项目配置选择文本模型，传入 Pydantic schema 作为 `response_schema` 强约束 JSON 结构
5. **Pydantic 验证与写回** — LLM 只产出视觉层，后端按条目 id 写回正式脚本，内容字段不进 LLM 输出，从工程上杜绝其经 Structured Outputs 漂移：
   - narration → `NarrationVisualEpisodeScript`（`segment_id` + image_prompt + video_prompt；video_prompt 不含台词）
   - drama（storyboard，含 grid_storyboard）→ `DramaVisualScript`（`scene_id` + image_prompt + video_prompt）
   - ad 分镜 → `AdVisualScript`（`shot_id` + image_prompt + video_prompt）；ad 整份生成 → `AdEpisodeScript` 加 `new_assets`（storyboard）或 `AdReferenceFlatScript`（reference_video），新增资产按处理决定改写引用后与正式脚本同一次写入登记
   - reference_video → `ReferencePromptAuthoringFlatScript`：待编写单元按顺序各一段改写后的正文，台词逐字保留
6. **补充元数据** — `episode`（集 ID）、`content_mode`、`novel`（项目 title + 本集标题，无标题时为「第 {播出位置} 集」）、时间戳。这些字段对 LLM 隐藏（SkipJsonSchema），由后端从 `project.json` 注入，避免 LLM 幻觉污染下游消费方（如剪映草稿）。
   - 注：**任何骨架的剧本都不写入顶层 `generation_mode`**。生成模式是项目级事实（`project.json` 的 `generation_mode`，创建时锁定），剧本骨架种类本身即生成模式的体现；消费方一律读 `project.json` 分派，不得从剧本上找该字段。

## 输出格式

生成的 JSON 文件保存至 `scripts/episode_N.json`，核心结构：

- `title`：LLM 写入的剧集标题
- `episode` / `content_mode` / `novel`（含 title、chapter）：由后端 `_add_metadata` 注入，不依赖 LLM 输出
- 旁白/解说：`segments[]`（每个分镜含 novel_text、duration_seconds、segment_break、出场角色 / 场景 / 道具 —— 内容确认时从脚本规划转入，之后在正式脚本上修改；image_prompt、video_prompt —— 由 prompt_authoring 生成）
- 剧情演绎：`scenes[]`（每个分镜含 image_prompt、video_prompt、duration_seconds，以及内容确认时从脚本规划转入的 utterances、source_text、characters_in_scene 等）
- 广告/短片：`shots[]`（每个分镜含 section、voiceover_text、products_in_shot、image_prompt、video_prompt、duration_seconds 等）；总时长偏离 `target_duration` 超阈值仅日志提醒，不阻塞保存
- 参考生视频：`video_units[]`（每个视频单元含 `text`、`duration_seconds` 等）
- `metadata`：created_at、updated_at、generator

条目数与全集总时长不落盘：它们逐读剧本即得，由项目摘要读时计算，落一份只会与正文漂移。

## `--dry-run` 输出

打印将发送给文本模型的完整 prompt 文本，不调用 API、不写文件。用于检查 prompt 质量和长度。

> 两种生成模式（storyboard / reference_video）在 narration / drama 下的数据路径、脚本规划子智能体、schema 选择详见 `.claude/references/generation-modes.md`；ad 的路径见项目 `CLAUDE.md`（源文件 `CLAUDE.ad.md`）。
