# jd-resume-match MCP Server（可复算评分 + 原文证据引用）

> 📦 **所属套件**：[ouba-classmate（欧八同学 AI 求职与创作 Skills 套件）](https://github.com/ouxxyy/ouba-classmate)

本目录提供 `jd-resume-match` 的标准 **Model Context Protocol (MCP)** 服务端实现（命名空间：`io.github.ouxxyy/jd-resume-match`）。
只暴露一个专注工具：`match_resume(jd, resume)`，按照 `jd-match-rubric/0.1.0` 规则返回：
- **可复算分数（`score`）** 与完整权重计算式 `floor(100 * Σ(weight * coef) / Σweight + 0.5)`
- **逐条 JD 要求的简历原文行号引用**（`L1..Ln`）与匹配关键词
- **证据缺口清单（`evidence_gaps`）**

## 隐私与安全边界
- **纯本地运行**：仅依赖 Python 3.9+ 标准库，通过 `stdio` 与宿主通信。
- **零网络请求**：不会发起任何外网请求，不会上传任何简历或 JD 数据。

## 快速运行与自检

使用 `uvx` 直接从 GitHub 启动：

```bash
uvx --from "git+https://github.com/ouxxyy/jd-resume-match#subdirectory=mcp" jd-resume-match-mcp --self-test
```

或在本地使用 `uv` 创建虚拟环境运行：

```bash
cd mcp
uv venv .venv
.venv/bin/python -m jd_resume_match_mcp.server --self-test
```

## 宿主配置片段（Claude Desktop / Claude Code / Cursor / Codex）

```json
{
  "mcpServers": {
    "jd-resume-match": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/ouxxyy/jd-resume-match#subdirectory=mcp",
        "jd-resume-match-mcp"
      ]
    }
  }
}
```
