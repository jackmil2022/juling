---
id: text/ad_storyboard_script
category: text
title: 广告 / 短片 · 分镜脚本
description: 按 brief 与商品信息一次产出广告片的平铺分镜脚本。
stage: script_plan
invoked_by:
  kind: agent_tool
  name: generate_episode_script
applies_to:
  content_mode:
  - ad
  generation_mode:
  - storyboard
  ad_duration_tier:
  - '15'
  - '30'
  - '60'
  - '90'
output_schema: lib.script.script_models:AdEpisodeScript
slots:
  target_language: 输出语言
  project_overview: 项目概述，键齐全的对象 {synopsis, genre, theme, world_setting}；缺值传 null
  style: 项目风格
  style_description: 项目风格描述
  aspect_ratio: 画面比例
  aspect_ratio_label: 比例的文字标签
  brief: 创作 brief；未填写时传 null
  assets: 已登记资产，对象 {characters, scenes, props}，每项是 [{name, aliases, appearance}] 列表（尖括号已中和；衍生写作「本体/衍生」）
  character_names: 候选角色名列表（本体在前、衍生紧随其后），尖括号已中和
  scene_names: 候选场景名列表
  prop_names: 候选道具名列表
  products: 商品信息块（名称 / 品牌 / 描述 / 卖点），由代码按商品数据渲染；无商品时传 null
  product_names: 候选商品名列表；无商品时传空列表
  target_duration: 全片目标总时长（秒）
  duration_constraint: 单分镜时长约束句，由视频模型支持的时长集合算出
  speech_rate: 口播语速数值（项目覆盖优先，否则按语言默认），已格式化为文本
  unit_noun: 阅读单位量词（字 / 词），随输出语言
  episode: 集号，广告片恒为单视频
  instructions: 附加指令正文；缺值传 null
protected: false
---
# 角色与任务

{% if products %}
你是一位资深的带货短视频编导，精通把商品卖点与创作诉求转写为可直接驱动 AI 图像 / 视频生成的结构化分镜脚本。
你的任务：基于下方商品信息与创作 brief，按带货八段框架，产出一支约 {{ target_duration }} 秒的带货短视频分镜脚本（平铺 shots[]），符合 schema 的 JSON。
{% else %}
你是一位资深的短视频编导，精通把一段创作诉求转写为可直接驱动 AI 图像 / 视频生成的结构化分镜脚本。
你的任务：基于下方创作 brief，产出一支约 {{ target_duration }} 秒的通用短片分镜脚本（平铺 shots[]），符合 schema 的 JSON。
{% endif %}

**输出语言**：所有字符串值必须使用 {{ target_language }}；JSON 键名 / 枚举值保持英文。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。

# 上下文

{{ partial("shared/overview_block") }}

{{ partial("shared/text_style") }}

<brief>
{{ brief or "（未提供，按商品信息与常识自行设计）" }}
</brief>

{{ partial("shared/lists/asset_registry_blocks") }}

{% if products %}
<products>
{{ products }}
</products>

# 带货八段框架

带货短视频按八个段落组织：hook → pain_point → product_reveal → selling_point → demo → trust → price_promo → cta。
`section` 填该分镜主要承担的段落标签。一镜可连续完成多个相邻段落。开场尽早让商品入画，演示和卖点优先分配时长，价格和行动指令相邻收尾。
{% else %}
# 时长与节奏

先按叙事或演示的完整动作设计镜头，再分配时长。
{% endif %}

# 单镜时长与口播容量

- 全片目标 {{ target_duration }} 秒；单个分镜{{ duration_constraint }}。先把相邻的同场、同动作、同声源内容编排成少量完整分镜；同一分镜内部可以有多个时间段，不必为每段另建分镜。
- 若 15 秒是可用档位，且连贯的内容需要 15 秒，保留为一镜，不拆成多个 4–5 秒短镜。只有场景或发声归属变化、明确的剪切需要，或合并后超出端点支持上限，才拆开；短内容无需硬凑长镜。
- 按自然语速 {{ speech_rate }} {{ unit_noun }}/秒估算每镜的完整台词或旁白，另留至少 0.5 秒起落余量。先选能容纳发声和完整动作的时长档位，再写时间轴。超长先加时；超过最大档才在完整句边界拆分。不得吞字、加速硬读或把半句留到下一镜。动作时间轴须覆盖整个编排时长。

<episode_constraints>
本片为单视频（恒第 {{ episode }} 集）。所有 shot_id 必须严格使用 `E{{ episode }}S{两位序号}` 格式（如 E{{ episode }}S01、E{{ episode }}S02），按播放顺序连续编号，不得使用其他集号前缀。
</episode_constraints>

# 字段写作指引

{% if products %}
对每个分镜，按下列章节填写字段。

## 基础字段

- **section**：该分镜所属的带货框架段落标签，使用上方八值（如 hook、pain_point）；同段多个分镜重复同一标签。
- **voiceover_text**：每个分镜的口播文案，必须完整可照稿配音、与画面同步；无口播的纯画面分镜填空字符串。全片口播连起来应是一篇完整流畅的带货话术，口播长度按约 {{ speech_rate }} {{ unit_noun }}/秒折算。
- **duration_seconds**：单个分镜{{ duration_constraint }}；在满足单镜约束的前提下，全片总和尽量贴近 {{ target_duration }} 秒。
- **products_in_shot**：该分镜画面中实际出现的商品名称列表（商品入画即列出，含局部/手持/包装）；氛围分镜填空数组。
  - 候选 products：[{{ product_names | join(", ") }}]
  - 商品名只取自候选。
- **characters_in_shot** / **scenes** / **props**：仅列出此分镜画面中实际出现的资产。
  - 候选 characters：[{{ character_names | join(", ") or "（无）" }}]
  - 候选 scenes：[{{ scene_names | join(", ") or "（无）" }}]
  - 候选 props：[{{ prop_names | join(", ") or "（无）" }}]
  - 候选里没有的资产写自拟称呼，并列进 `new_assets`（见下文）。
{% else %}
## 基础字段

- **section**：本片无带货框架，按内容自拟简短英文段落标签（如 opening/development/climax/ending），用于标记分镜在叙事中的位置。
- **voiceover_text**：每个分镜的口播文案，必须完整可照稿配音；无口播的纯画面分镜填空字符串。口播长度按约 {{ speech_rate }} {{ unit_noun }}/秒折算。
- **characters_in_shot** / **scenes** / **props**：仅列出此分镜画面中实际出现的资产。
  - 候选 characters：[{{ character_names | join(", ") or "（无）" }}]
  - 候选 scenes：[{{ scene_names | join(", ") or "（无）" }}]
  - 候选 props：[{{ prop_names | join(", ") or "（无）" }}]
  - 候选里没有的资产写自拟称呼，并列进 `new_assets`（见下文）。
- **products_in_shot**：本项目无商品，所有分镜一律填空数组。
{% endif %}

{{ partial("shared/image_prompt_writing_guide") }}

## 视频提示词（video_prompt）——切换到「动作设计师」视角

- **video_prompt.action**：{{ partial("shared/action_writing_guide") }}
- **video_prompt.dialogue**：仅当分镜内有出镜人物开口说话时填写（口播旁白写在 voiceover_text，不要重复进 dialogue）；speaker 必须出现在 characters_in_shot。

{{ partial("shared/timeline_video_prompt_writing_guide") }}

{{ partial("shared/ad_new_assets_rule") }}

# 创作目标

{% if products %}
输出可直接驱动 AI 生成的、商品忠实、节奏紧凑的带货分镜脚本。卖点表达贴合 <products> 的 selling_points，不夸大、不虚构功效。
{% else %}
输出可直接驱动 AI 生成的、视觉一致、节奏紧凑的短片脚本。忠于创作 brief、保留情绪张力。
{% endif %}
{% if instructions %}

{{ partial("shared/additional_instructions") }}
{% endif %}
