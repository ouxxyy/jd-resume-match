# Case C 手算推导（case-c-2yr-brand-mkt）

MYW-69 迁移测试材料：2 年经验品牌营销（early_career），未参与小样设计。画像设计目标——**高分仍被硬门槛否决**：主目标 70 分恰好踩在「优先投」分数线上，但年限一票条件不满足，按决策表第 1 条（unmet 门槛 → hold）优先于第 3 条（≥70 → prioritize）判「先暂缓」。

## job-c1 品牌营销主管（marketing）→ 70，建议 hold

| req | importance | w | status | coef | 贡献 |
|---|---|---|---|---|---|
| r1 独立策划执行整合营销活动 | must | 3 | supported | 1.0 | 3 |
| r2 社媒矩阵日常运营 | must | 3 | supported | 1.0 | 3 |
| r3 投放 ROI 与内容数据复盘 | must | 3 | partial | 0.5 | 1.5 |
| r4 熟练 Excel | must | 3 | supported | 1.0 | 3 |
| r5 对接达人并管理合作内容 | normal | 2 | supported | 1.0 | 2 |
| r6 预算管理经验（优先） | bonus | 1 | partial | 0.5 | 0.5 |
| r7 抖音信息流投放（优先） | bonus | 1 | unmet | 0 | 0 |
| r8 广告学/市场营销专业（优先） | bonus | 1 | supported | 1.0 | 1 |
| r9 SQL 基础（加分） | bonus | 1 | unclear | 0 | 0 |
| r10 协助带教初级成员 | normal | 2 | unknown | 0 | 0 |

Σ权重 = 20，Σ贡献 = 14 → floor(100×14/20 + 0.5) = **70**；未知项 2（r9 unclear + r10 unknown）。

门槛：g1 本科 met（ev-c8）；g2 三年以上经验 **unmet**（ev-c10：2024.07–2026.06 整两年，写得清楚、不够长）。
建议推导：存在 unmet 门槛 → **hold**（命中决策表第 1 条即停；若无此门槛，70 ≥ 70 且 2×3=6 ≤ 10 会走第 3 条 prioritize——分数条件「本来够格」，被门槛否决，这正是本案例要演示的边界）。

## job-c2 电商运营专员（operations）→ 63，建议 revise_then_apply

| req | importance | w | status | coef | 贡献 |
|---|---|---|---|---|---|
| p1 店铺日常运营与商品管理 | must | 3 | unmet | 0 | 0 |
| p2 店铺大促策划与直播统筹 | must | 3 | partial | 0.5 | 1.5 |
| p3 抖音/小红书内容生态 | normal | 2 | supported | 1.0 | 2 |
| p4 店铺转化数据优化建议 | normal | 2 | partial | 0.5 | 1 |
| p5 熟练 Excel | must | 3 | supported | 1.0 | 3 |
| p6 电商/快消背景（优先） | bonus | 1 | supported | 1.0 | 1 |
| p7 私域社群/用户运营（优先） | bonus | 1 | supported | 1.0 | 1 |

Σ权重 = 15，Σ贡献 = 9.5 → floor(100×9.5/15 + 0.5) = **63**；未知项 0。

门槛：g1 本科 met；g2 大促夜间直播值班 **pending_confirmation**（简历与追问均无信息，不从「没写」推断）→ 命中决策表第 2 条 → **revise_then_apply**。

## 变体（ans-c1：3000 元抖音助推测试盘，与代理联合盯盘）→ job-c1: 80

- r3 partial → supported（+3×0.5 = +1.5）：该条衡量复盘能力而非独立操盘，投放侧参与证据补齐第二块数据；
- r7 unmet → partial（+1×0.5 = +0.5）：真实投放接触但覆盖不全，不冒充独立操盘。

Σ贡献 14 → 16 → floor(100×16/20 + 0.5) = **80**。年限门槛不动、建议仍 hold——**涨分不翻案**（表达层 variant_note 以此为教学点）。

## 表达迁移要点（对应 content-standards / editorial.json）

1. 首屏先答三问：70 分只作背景，「先别投 + 为什么（年限一票条件）+ 先做哪件（五分钟问 HR）」。
2. 「协助」保留教学：rw-c3 反向排雷——不是删词，是死保一个诚实词（对照 Case A 的「独立」禁增）。
3. 「没写清 ≠ 不会」：r9 SQL 自述无佐证记「没写清」；「看不出 ≠ 没做过」：r10 带教记「看不出来」。
4. 变体口径：分数变化只来自新增事实（3000 元测试盘），文案明说「涨的是事实，不是句子」。
5. 发布文案三标题分别锚定：门槛发现（1）/ 诚实词发现+改写（2/3）/ 待补发现+行动（3/2）。
