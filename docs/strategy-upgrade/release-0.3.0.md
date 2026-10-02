# v0.3.0 安装与发布准备

日期：2026-10-02。用户已明确授权本地安装及发布到其 GitHub。

- 目标仓库：https://github.com/ouxxyy/jd-resume-match，公开，main；从当前上游历史正常提交，不重写开发仓库或远端历史。
- 本地唯一源目录：`.agents/skills/jd-resume-match`；Claude Code 的同名入口指向它。没有修改宿主配置或其他 Skill。
- 安装包：`jd-resume-match-0.3.0.zip`，715589 字节，payload 106 文件，ZIP 109 文件。
- SHA-256：`a09d9307b390691f282fee5978e149c88d13676d1da986857508d0d00b3b09df`。
- 干净目录安装、逐文件 SHA-256 校验、新版策略渲染和成员卡生成通过。真实安装副本也成功渲染，PNG 导出为 1080×1440。
- 上游安装入口的仓库根/ZIP 两种布局兼容保留；已更新公开 README，作者区、二维码及个人主页链接保留。
- 只发布代码、规范、测试、公开说明与合成案例；运行日志、私人材料目录、API 密钥及本机绝对路径不进入新发布内容。
- 初次公开源码测试因 dist 演示产物尚未生成而跳过一个浏览器测试；生成正式演示产物后再跑完整测试，结果见下。

```text
python3 -m unittest discover -s tests -v
Ran 270 tests — OK（最终公开源，无跳过项）
sh install.sh <干净目录的skills根>
冒烟校验通过；106 文件逐字节一致
python3 <实际安装副本>/scripts/render_editorial.py ...
报告、成员卡、案例卡、预览及发布草稿生成成功
python3 <实际安装副本>/scripts/export_png.py ...
[成功] 136105 字节，1080×1440
```

本文件记录发布前的实际验证；远端提交、tag 和 Release 下载资产需在发布后读回核对。
