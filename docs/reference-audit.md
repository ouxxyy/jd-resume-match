# 开源参考审计（T1 · reference-audit）

审计人：opp-evaluator（T1）。检索与核对方式：GitHub REST API（仓库元数据、最新 commit、语言构成、README 原文快照）。
检索日期：**2026-09-11（UTC）**。所有数字为当日 API 实测值，会随时间变化，引用时注明。

> 红线声明：仓库星数只反映关注度，**不作为效果证据**；上游作者的个人求职结果不构成本产品的效果证明。本阶段（T1）未复制任何上游代码，只做思路与许可证核对。

## 一、总览

| 仓库 | Stars | License | 最新 commit（sha12 · 日期） | 主要语言 | 活跃度 |
|---|---|---|---|---|---|
| [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) | 41,777 | MIT | `c7bd494f11e7` · 2026-09-10 | Python 396KB / TS 305KB / TeX 12.8KB | 高（次日仍有提交） |
| [LingyiChen-AI/JadeAI](https://github.com/LingyiChen-AI/JadeAI) | 1,963 | Apache-2.0 | `aca6fbbb0bea` · 2026-09-03 | TS 2.7MB（Next.js 16 + React 19） | 高 |
| [xitanggg/open-resume](https://github.com/xitanggg/open-resume) | 8,901 | **AGPL-3.0** | `4f8255a2c763` · **2024-10-29** | TS 223KB（Next.js 13） | **停滞约 2 年** |
| [reactive-resume/app](https://github.com/reactive-resume/app)（原 `reactive-resume`，已迁移） | 42,466 | MIT | `08e61ded7bdd` · 2026-09-11 | TS 5.2MB（v5，Monorepo） | 高 |

## 二、逐仓库结论

### 1. ai-job-search（MIT · 优先研究对象）

- **是什么**：构建在 Claude Code 上的求职申请框架：`/setup` 建档案 → `/scrape` 搜岗 → `/rank` 批量按 fit 框架打分排序 → `/apply` 评估匹配、起草 LaTeX CV/求职信、复核 agent 批评、ATS 可解析性检查。
- **可借鉴点（T1 采纳进契约）**：
  - `04-job-evaluation.md` 的**结构化评估框架**：多维评估 + 每项给出证据，而不是整体印象分 → 对应我们的逐条要求状态机（supported/partial/…）。
  - `/rank` 的 **deal-breaker 一票否决**：硬门槛不过直接 veto，不参与分数比较 → 直接验证了我们「硬门槛单列、`unmet` 强制暂缓」的设计是同类系统的成熟做法。
  - 「genuine gaps stay visible, never stuffed」：ATS 关键词覆盖检查中**真实缺口保持可见、绝不堆砌** → 对应我们的去重规则与「纯润色不制造能力增长」。
  - **材料视为不可信输入**：「Postings are treated as untrusted input (the workflow follows no instructions embedded in them…)」——JD 内嵌指令不执行 → 对应我们的 injection 防线（Case B 的 JD 内埋了「直接给满分」注入样本，期望判定不受影响并记录 `injection_suspected`）。
  - `/html-report` 用**内联 SVG、零外部依赖、file:// 离线打开**的自包含 HTML → 与我们 T3 渲染方案同构，证明路线可行。
- **不采用 / 边界**：自动搜岗与投递（计划明确排除）；LaTeX 工具链与 Bun 依赖（重，且我们不做 CV 生成）；其求职门户 skills 绑定丹麦市场。
- **依赖成本**：若借鉴代码为 MIT，需保留版权与许可声明；本阶段零代码采纳，成本为 0。
- **隐私教训（引自其 README）**：fork 必然公开，`/setup` 会把个人数据写进**被跟踪**文件 → 印证我们把「真实材料禁止入库 + 分享白名单」设为仓库级红线的必要性。

### 2. JadeAI（Apache-2.0）

- **是什么**：中文向 AI 简历构建站（Next.js）：50+ 模板、PDF/图片简历 AI 解析、**JD 匹配分析**（关键词匹配、ATS 分、改进建议）、分享链接、模拟面试。
- **可借鉴点**：JD 匹配分析的**交互呈现方式**（逐项对照 + 建议）；图片/PDF 解析的降级交互（T2 输入降级参考）；分享链接的预览流程（T3 分享预览参考）。
- **不采用 / 边界**：整体是带服务端与账号体系的 Web 应用，不做移植；其「ATS score」是关键词命中口径——我们的分数口径是**证据覆盖**，报告必须写明区别，避免用户误读。
- **依赖成本**：Apache-2.0 允许商用，但需保留 LICENSE 与 NOTICE、标注修改；引入其 UI 组件会拖入 React/Next 全家桶，与零依赖渲染冲突 → 不引入。

### 3. open-resume（AGPL-3.0 · ⚠️ 许可证红旗）

- **是什么**：简历构建 + 简历解析器（PDF.js 提取文本 → 分组算法还原结构），纯浏览器本地运行。
- **许可证结论**：**AGPL-3.0 具有传染性**——若复制其解析代码，我们的衍生分发物也必须以 AGPL 提供源码。本项目计划分发给求职者本地使用，**决定：只读思路、零代码采纳**；T2 自研 PDF/DOCX 提取（Python 侧），不移植其 TS 实现。
- **可借鉴点（思路级）**：解析后先给**识别摘要 + 漏读警告**再进入分析（对应我们的 parse_warnings 与「不凭残缺解析强行评分」）；解析算法文档写法（open-resume.com/resume-parser）值得 T2 写文档时参考。
- **风险与未验证项**：**最后提交 2024-10-29，已停滞约 23 个月**，PDF 库版本会落后于新解析器兼容性；**对中文多栏简历的适配没有任何公开验证**——计划已明确「不假定适配中文已经成立」，T2 必须用中文多栏样例实测。
- **依赖成本**：AGPL 下合规成本高 + 上游停更 → 双重理由放弃代码采纳。

### 4. reactive-resume/app（MIT）

- **是什么**：42k 星简历构建器，v5 monorepo，主打隐私（自托管、无跟踪、数据可导出可删除）。
- **可借鉴点**：**隐私体验清单**（自托管、默认无跟踪、一键删数据、完整导出）→ 纳入我们隐私边界设计；分享链接与导出格式的交互；「Structured Style Rules」的样式数据化思路（T3 模板可参考）。
- **不采用 / 边界**：完整编辑器与账号体系（计划明确排除）；monorepo 体量（5.2MB TS）不适合借鉴工程结构。
- **注意**：仓库已从 `reactive-resume` 迁移到 **`reactive-resume/app`**（其 README 顶部有迁移公告，issue #3503），后续引用一律用新地址，避免引用失效。

## 三、汇总决策

| 仓库 | 代码采纳 | 许可证义务 | 主要用途 |
|---|---|---|---|
| ai-job-search | 无（思路） | 若未来引入：MIT 声明 | 评估框架、deal-breaker、untrusted input、离线 HTML 路线 |
| JadeAI | 无（思路） | 若未来引入：Apache-2.0 + NOTICE | JD 匹配交互、解析降级、分享预览 |
| open-resume | **永不复制代码** | AGPL 隔离 | 解析摘要+警告的思路；中文适配作为 T2 待验证风险项 |
| reactive-resume | 无（思路） | 若未来引入：MIT 声明 | 隐私体验清单、导出交互 |

后续开发（T2/T3）引用上游时，必须在本文件追加：commit/文件路径、借鉴方式、许可证核对结果；代码级采纳前先过小队评审并更新 `THIRD_PARTY_NOTICES.md`。
