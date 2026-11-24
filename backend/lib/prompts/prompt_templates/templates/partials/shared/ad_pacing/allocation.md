通用规则（适用于全部档位）：

- hook 与 cta 保持简洁；加长的秒数优先给 selling_point/demo，其次 trust
- price_promo 永远紧贴 cta 构成「促单收尾块」
- 即使 hook 不是商品画面，商品也应在前 3 秒内入画（文字/局部/手持均可）
- 下表的秒数、累计时间和镜头数只作内容配比参考，不是单镜时长要求。优先满足每个分镜或视频单元的时长硬约束；可把相邻短段落合并进一个镜头，或将超出上限的内容拆开。不要为凑分镜数或总时长输出低于下限的条目。
- 30 秒档为默认推荐档；90 秒档用「小故事」组织而非平铺卖点，仅适合高客单/需教育的商品

{{ variant("shared/ad_pacing/tier", ad_duration_tier) }}
{% if off_tier_target_duration %}

目标总时长 {{ off_tier_target_duration }} 秒不在审定档位内，参考最近的 {{ ad_duration_tier }} 秒档调整配比；时长增减优先给 selling_point/demo，其次 trust。
{% endif %}
