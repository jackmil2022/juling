---
id: reference_video/unit
category: video
title: 参考生视频
description: 参考生视频单元的完整提示词，由参考素材声明、单元正文、风格与负向约束三段组成。
stage: reference_video
invoked_by:
  kind: generation_task
  name: reference_video
applies_to: {}
slots:
  declarations: 第一段：主体绑定（<X>@图片N）、同一角色的形态声明与声音声明（@音频N）；无参考素材时为空
  body: 第二段：单元正文，mention 已换成主体记号，角色台词已重组，裸旁白记号保留并交给视频模型生成
  style: 项目画风
  style_description: 项目风格描述
  co_present_characters: 同框的不同角色，本体与衍生合并计一个；不足两个时为空
  products: 随请求发出参考图的商品名，按首现顺序去重；无商品参考图时为空
protected: false
---
{{ declarations }}

{{ body }}

{{ partial("shared/media_style") }}
{{ partial("reference_video/unit/avoid") }}
{% if products %}

商品高保真还原（最高优先级）：按商品参考图原样呈现商品{{ partial("reference_video/unit/lists/products") }}，{{ partial("shared/product_fidelity") }}。项目画风只作用于商品以外的画面元素。
{% endif %}
