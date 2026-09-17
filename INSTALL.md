# jd-resume-match skill 安装与使用（v0.2.0）

「JD vs 简历匹配度打分器」：用户提交一份简历 + 一个或多个 JD，经初诊和最多一轮（3 个可跳过）追问，获得可复算、有证据引用的匹配评分报告、自包含 HTML 求职体检单，以及编辑批注风的默认交付（报告 + 成员版分享卡 PNG 1 张 + 案例版卡片 PNG + 小红书文案，均为 1080×1440）。
**分数只衡量「简历证据对 JD 要求的覆盖」，不是能力总分、ATS 官方分或面试概率。**

---

## 1. 环境要求

| 项 | 要求 |
|---|---|
| Python | 3.9+（**仅标准库，零第三方依赖**，无需 pip install） |
| 宿主智能体 | 任意支持 `SKILL.md` 规范的 AI 编码助手（Claude Code / ZCode / Codex CLI 等）；其他智能体可手动跟随 SKILL.md 流程执行 |
| 网络 | 安装与本地渲染不需要联网；仅「JD 链接抓取」为可选联网功能 |
| 浏览器 | 仅导出 PNG（默认链路卡片 1080×1440、报告长图；旧链路 HTML 分享卡 800×1000）时需要；任选 Chrome / Chromium / Edge，不装也能交付全部 HTML/MD 资产 |

## 2. 安装

仓库根目录就是 skill 本体（`SKILL.md` 在根部），三种方式任选：

### 方式 A：git clone（推荐）

```bash
# ZCode / 其他使用 ~/.zcode/skills 的宿主
git clone https://github.com/ouxxyy/jd-resume-match.git ~/.zcode/skills/jd-resume-match
# Claude Code
git clone https://github.com/ouxxyy/jd-resume-match.git ~/.claude/skills/jd-resume-match
```

clone 即可用，无需构建。`tests/`、`docs/`、`assets/` 只是仓库附属（测试与文档），不参与 skill 运行，不需要可删。

### 方式 B：install.sh

```bash
./install.sh                    # 默认装到 ~/.claude/skills/
./install.sh ~/.zcode/skills    # 或指定任意 skills 根目录
```

脚本行为：只写入 `<目标>/jd-resume-match/` 一个目录；**目标已存在同名非空目录时拒绝安装、不覆盖任何文件**（`--force` 才覆盖）；安装完自动跑一次校验器冒烟检查。在仓库根或 Release 压缩包解压目录内运行均可（自动识别两种布局）。

### 方式 C：Release 压缩包 / 手动复制

从 GitHub Releases 下载 `jd-resume-match-<版本>.zip`（附 sha256 校验值），解压后运行包内 `install.sh`，或把 `jd-resume-match/` 整个目录复制到宿主的 skills 根目录（如 `~/.claude/skills/`、`~/.zcode/skills/` 或项目内 `.claude/skills/`）。本 skill 不写任何用户级配置文件；卸载 = 删除这一个目录。

压缩包内 skill 目录结构：

```text
jd-resume-match/
├── SKILL.md            # 分析流程（智能体读这个）
├── references/         # 评分契约 + 数据契约 + 表达契约 + 编排契约 + 品牌配置 + 岗位量尺
├── scripts/            # 提取/校验/评分/渲染/分享/编排渲染/PNG 导出 确定性脚本
├── templates/          # 报告 HTML 模板（旧链路）
├── examples/           # 合成示例（expected.json + editorial.json 成对）
└── THIRD_PARTY_NOTICES.md
```

### 安装后验证（不依赖智能体，纯脚本侧）

```bash
python3 <安装路径>/jd-resume-match/scripts/validate_report.py \
  --input <安装路径>/jd-resume-match/examples/case-b-2yr-data-dev/expected.json
# 期望输出包含 PASS / 合法（结构+引用+隐私校验通过）
```

智能体侧验证：对宿主说「用 jd-resume-match 体检 examples/ 里的合成简历」即可跑完整流程。

## 3. ⚠ 格式化 hook 事件提示（发布/复用前必读）

**在装有全局格式化 hook（如 prettier PostToolUse）的环境里运行本 skill，hook 可能在智能体写文件时自动重排仓库内文件格式**。开发过程中端到端实测发生过一次：全局 prettier hook 重排了 `SKILL.md` 的表格与代码块（Markdown 列对齐、引号统一等），导致与契约文件产生非预期 diff。

建议：

- 发布或对外复用前，**在干净目录（无全局 hook）验证一次**完整流程；
- 在为本仓库/工作目录配置的 hook 设置中禁用全局格式化器，或把 `SKILL.md`、`references/`、`examples/` 加入格式化忽略清单；
- 复现特征：`git diff` 出现大量「表格列对齐 / 引号风格」类改动而无人编辑——即是 hook 所为。

## 4. 使用（智能体执行视角)

安装后对智能体说：「用 jd-resume-match 分析我的简历 + 这个 JD」。完整流程见 `SKILL.md`，六步概览：

1. **收集输入**：一份简历（PDF/DOCX/TXT/MD）+ 一个或多个 JD（文本/文件/链接）；
2. **提取（脚本）**：`python3 scripts/extract_resume.py --resume <简历> --jd-file <JD>... --output extraction.json`；
3. **初诊（模型）**：拆解 JD 要求、逐条在简历原文定位证据，产出报告 JSON（不算分）；
4. **澄清轮**：最多 3 个可整体跳过的问题；多岗位时「选主目标」计入 3 问；
5. **校验与评分（脚本，唯一算分口径）**：`validate_report.py` → `score_report.py --apply`（校验失败拒绝写盘）；
6. **渲染交付（默认链路：编辑批注风报告 + PNG 分享卡）**：撰写 `editorial.json` → `render_editorial.py` 生成报告 HTML + 卡片预览 + 单卡 HTML → `export_png.py` 导出 **1080×1440 PNG**（成员版默认 1 张）。内容编排校验失败或 PNG 导出失败时明确报错、修复后重试——**不把仅 HTML 的旧报告或旧分享卡当成完成交付**；
7. **旧链路（仅兼容）**：`render_report.py`（报告 HTML）+ `build_share.py`（脱敏分享卡 HTML）保留以兼容既有调用，正常使用不得静默退回旧模板。

手动复算入口（人工复核分数时）：`python3 scripts/reference_score.py --show <case>/expected.json`。

## 5. 输入限制（诚实清单）

**简历 / JD 文件**

| 格式 | 支持度 | 说明 |
|---|---|---|
| .md / .txt | ✅ 推荐 | 中文材料首选，定位符为行号 |
| .docx | ✅ | OOXML；旧版 .doc 与加密文件明确拒绝，不猜测 |
| .pdf | ⚠️ 有限 | 仅「简单字体的文本型 PDF」可靠；**不做 OCR**；扫描件/图片型直接拒绝评分 |

**中文 PDF 特别说明（重要）**：中文 PDF 常见 CID/Type0 类字体，零依赖提取**不做解码**，结果大概率乱码。自 v0.1.1 起「乱码必有告警」由双防线保证（MYW-66 回修）：字体特征扫描覆盖压缩对象流（Chrome 打印 / 新版 Word / WPS 导出常见），另有提取输出乱码兜底检测——v0.1.0 中「乱码且告警不触发」的已记录缺陷已修复。但**告警不等于可解码**：中文材料请仍优先用 DOCX / TXT / 直接粘贴文本，PDF 仅用于英文或确认可复制出正确文本的文件。

**JD 链接**：尽力抓取（10 秒超时、2MB 上限）；需登录、反爬或动态渲染的页面会失败并引导粘贴全文。本 skill 不询问、不存储任何 API 密钥；分析过程由宿主智能体及其配置的模型处理，「离线」仅指报告浏览不需联网。

**其他**

- 加密 / 损坏 / 空文件 / 旧版 .doc：进入显式降级路径（有 `reason_code` + `guidance`），**无法评分时不伪装 0 分**；
- 评分口径：`references/scoring-rubric.md`（jd-match-rubric/0.1.0）是唯一标准；权重、门槛、建议全部由脚本按契约复算；
- 隐私：真实材料只在本地会话中处理；`build_share.py` 白名单脱敏 + `private_markers` 扫描；完整报告含材料细节，外发前需用户自行确认。

## 6. 示例与再生成

`examples/` 全部为**合成材料**（`synthetic: true`），无一真实简历/JD：

| 目录 | 岗位数 | 分数 | 演示重点 |
|---|---|---|---|
| `case-a-freshgrad-ops/` | 2（运营 75 / 产品 29，变体 86） | 应届生三态判定、多岗位排序、补充回答变体 |
| `case-b-2yr-data-dev/` | 2（数据 83 / 后端 17） | **多岗位示例**：强匹配优先投 + unmet 硬门槛强制暂缓 |
| `supplements/sup-market.*` | 1（64） | **单岗位示例**：unknown 投放经验、partial 校园资源 |
| `supplements/sup-design.*` | 1（42） | 单岗位：作品集门槛 pending（不推断「没有」） |
| `case-c-2yr-brand-mkt/` | 2（品牌 70 / 电商 63，变体 80） | **规则迁移验收案例**（MYW-69）：70 分踩线仍被年限一票条件否决（hold）、诚实词「协助」排雷、补充回答变体 |

重新生成示例资产（修改 `expected.json`、`editorial.json` 或模板后）：

```bash
# 1) 旧链路入库资产：报告与分享卡（确定性渲染，同输入必出同字节）
python3 scripts/render_report.py --input examples/<案例>/expected.json --output examples/<案例>/report.html
python3 scripts/build_share.py  --input examples/<案例>/expected.json --output examples/<案例>/share.html

# 2) 新链路发布素材（编辑批注风）：报告 HTML + 卡片预览 + 单卡 HTML + 小红书 MD
python3 scripts/render_editorial.py \
  --input examples/<案例>/expected.json --editorial examples/<案例>/editorial.json \
  --outdir dist/publish/<案例>
#    补充案例的编排文件在 examples/supplements/（sup-market.editorial.json 等）

# 3) 卡片 PNG（1080×1440，逐张导出；或打开 cards-preview.html 点「导出全部 PNG」）
python3 scripts/export_png.py --html dist/publish/<案例>/cards/card-01-cover.html \
  --out dist/publish/<案例>/cards/card-01-cover.png
#    报告整页长图：加 --width 1440（或 390）--fullpage

# 4) 分享 PNG（800×1000，旧分享卡规格；也可直接点 share.html 里「导出 PNG 图片」按钮）
python3 scripts/export_png.py --html examples/<案例>/share.html --width 800 --height 1000 \
  --out share.png

# 5) 改动评分相关内容后必须全量回归
python3 -m unittest discover -s tests -v   # 本仓库含 tests/；zip 分发包不含
```

**重生成检查清单**（render_editorial 校验器已强制执行，人工复核时对照）：

- 引号内一律 JD 原文 / 简历原文逐字（`jd_anchor`、放大镜 `raw_line` 均为逐字子串）；
- rationale 与 answers 无矛盾——补充回答未计入判定时，标准口径是「按简历正文算，追问回答计入需重跑」；
- 改写后文本数字逐个有出处、职责范围词（独立/主导/负责/带领/统筹）零新增；
- 没有内容编排数据时不出爆款标题、不拼卡片（宁缺毋滥）；
- 卡片与发布文案生成前过 private_markers / 邮箱 / 手机号扫描。

补充案例（supplements）复用 Case A 的合成简历，JD 在各自 `*-jd.md`；期望分数对账表见 `examples/README.md`。

## 7. 第三方声明

见 `THIRD_PARTY_NOTICES.md`：本项目未复制、未引入任何上游仓库代码（仅思路级研究，留痕于 `docs/reference-audit.md`），当前**无附带许可证义务**；其中 open-resume（AGPL-3.0）已明确决定不采纳其代码。

## 8. 已知限制

- 分数语义 = 简历证据对 JD 要求的覆盖度（rubric 0.1.0 校准口径，基于 4 合成案例 7 岗位视角校准）；非能力评价、非 ATS 分、非面试概率，不宣称任何「XX% 置信度」。
- 初诊 / 澄清轮 / 证据引用属模型侧能力，质量依赖宿主智能体；脚本侧（提取、校验、评分、渲染）为确定性实现，同输入必出同输出。
- 中文 PDF 的 CID 乱码**告警缺失**缺陷已在 v0.1.1 回修（双防线，MYW-66，见 §5）；但提取仍不做 CID 解码，中文 PDF 材料一律建议转文本/DOCX（「中文 PDF 能直接读」属后续候选，未实现）。
- 分享卡 PNG 由浏览器渲染，不同浏览器字体渲染略有差异；HTML 分享卡本身不依赖浏览器版本。
