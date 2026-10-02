# 整份结构与分析策略升级验收

日期：2026-10-02。这是发布前功能验收记录；v0.3.0 的安装与发布结果另见 release-0.3.0.md。

## 结果

- editorial/voice 升至 0.3.0；报告/rubric 保持 0.1.0。新增全篇库存、结构蓝图、价值链、招聘疑虑、关键词诊断及修改优先级。主目标限定、一轮最多三问、重点改写与三项行动保留。
- 270 项全量测试通过（原 215 项 + 新增 55 项），包括浏览器导出测试。原七组评分案例全部复算通过；分数、未知项和投递建议未改。
- 冻结 Schema 负例探针：REJECT 383，LEAK/TRACEBACK/ERROR/WEAK 均为 0。探针使用原 Schema 展开本地引用并应用当前版本的条件 required，未放宽约束。
- 原 REPORT_CSS 校验值不变；Case A 旧 HTML 固定摘要回归通过。独立审查也在内存核对 Case A/B/C 及旧版读取：HTML 与修改前一致。0.2.0 成员卡仍生成。
- 四种合成岗位视角，桌面 1440、手机 390，共八个视口均无横向溢出；折叠、目录跳转及复制处理通过。复制测试拦截了临时浏览器的 clipboard API，验证处理与按钮反馈，不把它描述为系统剪贴板权限证明。
- 正式 `export_png.py` 导出成员卡成功，1080×1440。报告截图与成员卡见本目录。

## 模型分析与结构前后对照

使用本机 Codex CLI（默认 gpt-6.1-sol，ephemeral、read-only、忽略用户配置）直接读取更新后的 SKILL 与规范，执行新的整份分析阶段。三个独立合成输入，另加同一应届输入的主目标切换；无公司调研、真实材料或用户配置修改。

评分报告先由现有确定性实现预校验，模型只生成 resume_strategy；提取、校验、复算、渲染和导出由原脚本整合验证。因此这证明新分析阶段和完整数据链路可配合，不代表模型每次都会一次生成合法编排。

| 合成场景 | 原顺序 | 新顺序 / 变化 | 分数 |
|---|---|---|---|
| 教育先行的在职运营 | 教育 → 工作 → 技能 | 工作 → 技能 → 教育 | 83，未因重排改变 |
| 较早工作更相关 | 最近行政在前，较早社群在后 | 社群任职前移，行政任职仍保留雇主/职位/日期 | 100，未因重排改变 |
| 应届生投数据分析 | 教育 → 项目 → 校园 | 项目 → 教育 → 校园 | 数据 83，研究 75 |
| 同一人改投统计研究 | 同一份原材料 | 教育 → 项目 → 校园，重新关联研究岗要求 | 数据仍 83，研究仍 75 |

正文覆盖检查：逐行核对合成简历正文均进入库存引用；文档封套标题和 synthetic 声明不算候选人经历。所有任职日期及团队成果归属已人工核对。项目、课程和校园均为合法证据，未写死“工作第一”。

可打开：

- [较早相关经历前移报告](../../examples/strategy-upgrade/older-relevant-work/preview/report.html)
- [应届数据岗报告](../../examples/strategy-upgrade/freshgrad-project/preview/report.html)
- [同一材料改投研究岗报告](../../examples/strategy-upgrade/freshgrad-project-research/preview/report.html)

各案例的 `analysis.raw.json` 保存原始模型策略（带合成声明及 private_markers），`editorial.json` 是最终经校验的编排。模型初稿混写已确认角色与未声明的职责范围时，严格校验拒绝；最终把事实字段限于原文已有角色/行为，将职责不明的疑虑列为待确认，未增加事实。首组把测试文档封套当待补材料的条目已删除。

## 实际命令及输出

```text
python3 -m unittest discover -s tests -v
初始沙箱运行：Ran 215 tests，FAILED (errors=1)
PermissionError: [Errno 1] Operation not permitted（Chrome 本地端口绑定）
授权环境基线：Ran 215 tests in 11.765s — OK
最终授权环境：Ran 270 tests in 3.906s — OK

python3 scripts/reference_score.py --check <七组既有 expected.json>
七组全部退出 0；逐岗结果见 golden-score-checks.json

python3 scripts/score_report.py --check <四种新视角的 report.json>
四种全部退出 0；数据/研究分数切换前后完全一致

python3 scripts/render_editorial.py --input <report.json> --editorial <editorial.json> --outdir <preview>
四种全部成功生成报告、成员卡、案例卡、预览与发布草稿

python3 docs/strategy-upgrade/check_browser.py
八个视口：scrollWidth == width；expand/navigation/copy_handler 全为 true

python3 scripts/export_png.py --html examples/strategy-upgrade/education-first-work/preview/member-card-01.html --out docs/strategy-upgrade/member-card-cli.png
[成功] 136653 字节，1080×1440

contract_negative_probe.py --schema <由冻结契约展开的临时Schema> --fixture <新版editorial> --must-contain 契约校验失败 --max-variants 9999 -- python3 scripts/render_editorial.py ...
REJECT 383 · LEAK 0 · TRACEBACK 0 · ERROR 0 · WEAK 0 · N/A 0

git diff --check
退出 0，无输出
```

模型命令形状为 `codex exec --ephemeral --ignore-user-config --sandbox read-only --output-schema <临时输出Schema> --output-last-message <临时JSON> - < analysis-prompt.txt`。首个请求的输出传输 Schema 被 API 拒绝：optional entry_kind 不满足 strict 输出的全部 required 要求。只调整临时传输 Schema，非经历项以 null 传输后删除该空字段恢复正式契约，未改变生产 Schema。

原始执行日志和初始沙箱失败片段留在本地；公开目录包含真实输出摘要、浏览器几何结果和合成模型场景摘要。

## 验证边界

结构校验能证明库存内的引用、归属和去向；正文是否完整，以及数字单位、因果、团队与个人贡献的语义仍需核对。本轮用合成正文覆盖与人工审阅补了这层；不宣称能机械证明所有真实材料的语义。未核验原始视觉版式时，格式观察保持未核验；本轮没有新增 OCR 或实际 ATS 系统测试。
