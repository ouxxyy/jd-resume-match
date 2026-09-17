# 黄金案例说明（examples/）

本目录全部为**合成材料**（JSON 内 `synthetic: true`）：人物、机构、数字均为虚构，专用于校准评分契约。禁止将真实简历/JD 提交进本仓库。

## 案例一览

| 目录 | 简历画像 | JD | 岗位类别 | 期望分数 | 演示重点 |
|---|---|---|---|---|---|
| `case-a-freshgrad-ops/` | 应届生（市场营销） | jd-1 新媒体运营 / jd-2 产品助理 | 运营 + 产品 | 75 / 29（变体 86） | supported/partial/unclear 三态、待确认门槛、多岗位排序、补充回答变体、注入边界外的正常判定 |
| `case-b-2yr-data-dev/` | 2 年经验（数据） | jd-1 数据分析 / jd-2 Python 后端 | 数据 + 研发 | 83 / 17 | 强匹配优先投；**硬门槛 unmet 强制暂缓**；unknown 群单列；JD 注入样本 |
| `case-c-2yr-brand-mkt/` | 2 年经验（品牌营销） | jd-1 品牌营销主管 / jd-2 电商运营 | 市场 + 运营 | 70 / 63（变体 80） | **70 分踩线仍被年限一票条件否决（hold）**；「协助」诚实词排雷；没写清≠不会、看不出≠没做过；主目标为暂缓岗时的行动写法 |
| `supplements/sup-market.*` | 同 Case A 应届生 | 市场专员 | 市场 | 64 | 投放经验 unknown、校园资源 partial |
| `supplements/sup-design.*` | 同 Case A 应届生 | 视觉设计师 | 设计 | 42 | 作品集门槛 pending（不推断「没有」）、Canva→Figma 工具差距 partial |
| `case-c-2yr-brand-mkt/` | 2 年经验（品牌营销） | jd-1 品牌营销主管 / jd-2 电商运营 | 市场 + 运营 | 70 / 63（变体 80） | **规则迁移验收案例**：70 分踩线被年限一票条件否决（hold）、诚实词「协助」不可删、投放补充回答变体 |

六类重点岗位（产品/运营/市场/数据/研发/设计）与两类资历（应届/1–3 年）均已覆盖。

## 内容编排文件（editorial.json）

每组案例另配 `editorial.json`（jd-match-editorial/0.1.0）：独立带版本的表达层数据，承载报告导语、关键发现、卡片文案与小红书标题正文。它**永不携带分数**（分数只来自 expected.json），且必须通过 `render_editorial.py` 的契约校验：引用可解析、JD/简历引号逐字、数字溯源、职责范围词零新增、内部话与私密标记禁入。四组案例的发布成品见开发仓库 `dist/publish/`。

## 如何人工复核（不信任机器时）

1. 打开案例目录的 `resume.md` 与 `jd-*.md` 原文。
2. 对照 `expected.json` 中每条 requirement：`jd_quote`（JD 原文摘录）+ `evidence[].quote`（简历原文摘录）+ `locator`（位置）+ `rationale`（判定理由）三者都应能在原文中逐字找到。
3. 对照 `case-a-freshgrad-ops/HAND-CALC.md` 的手算表核对分数。
4. 或直接跑机器复算：`python3 scripts/reference_score.py --check examples/<案例>/expected.json`。

## 期望分数对账表（rubric 0.1.0）

| job | 期望分 | 建议 | 依据 |
|---|---|---|---|
| job-a1 新媒体运营 | 75 | revise_then_apply（门槛 g2 待确认） | HAND-CALC.md 手算（MYW-61 复校 83→75） |
| job-a1 变体（ans-a1 后） | 86 | 不变 | answer_variants 可复算 |
| job-a2 产品助理 | 29 | revise_then_apply（门槛 g2 待确认） | 契约检查复算 |
| job-b1 数据分析 | 83 | prioritize | 决策表第 3 条 |
| job-b2 Python 后端 | 17 | hold（gate-b2-g2 unmet） | 决策表第 1 条 |
| job-s1 市场专员 | 64 | revise_then_apply | 决策表第 4 条 |
| job-s2 视觉设计 | 42 | revise_then_apply（作品集待确认） | 决策表第 2 条 |
| job-c1 品牌营销主管 | 70 | hold（年限门槛 unmet） | 决策表第 1 条；70≥70 但门槛否决 |
| job-c1 变体（ans-c1 后） | 80 | hold 不变 | 涨分不翻案 |
| job-c2 电商运营专员 | 63 | revise_then_apply（夜间值班待确认） | 决策表第 2 条 |
| job-c1 品牌营销主管 | 70 | hold（gate-c1-g2 三年经验 unmet，简历记两年） | 决策表第 1 条优先于第 3 条（70≥70 本可 prioritize） |
| job-c1 变体（ans-c1 后） | 80 | 不变（仍 hold） | answer_variants 可复算；涨分不翻案 |
| job-c2 电商运营 | 63 | revise_then_apply（夜间值班门槛待确认） | 决策表第 2 条 |
