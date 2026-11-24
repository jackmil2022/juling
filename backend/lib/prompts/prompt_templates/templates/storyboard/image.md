---
id: storyboard/image
category: storyboard
title: 参考图
description: 分镜参考图的完整提示词，由风格、输入素材清单与分镜画面组成。
stage: storyboard_image
invoked_by:
  kind: generation_task
  name: storyboard
applies_to: {}
slots:
  style: 项目画风
  style_description: 项目风格描述
  reference_images: 已序列化的参考图槽位、名称及用途清单，无参考图为空
  structured_body: 已序列化的 Scene（含镜头、光线与氛围），纯文本形态为空
  text_body: 纯文本正文，结构化形态为空
protected: false
idempotent: true
---
{{ partial("shared/media_style") }}
{% if reference_images %}
{{ partial("storyboard/image/references") }}
{% endif %}
{% if text_body %}

{{ text_body }}

{% else %}
{{ structured_body }}
{% endif %}
尺度与空间关系：正文中的人物、商品、道具与场景比例，以及站位、距离、遮挡、接触、支撑、受力和透视关系，已经由文本 Agent 根据参考素材、已知尺寸和本镜描述预先确定。图像模型只执行正文明确写出的具体关系，不自行推断主体大小、位置、距离或接触方式；正文未明确的未知尺寸不补写。
{{ partial("storyboard/image/avoid") }}
