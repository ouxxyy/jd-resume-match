# pdf-multicolumn 证据存档（多栏中文 PDF 实测）

| 文件 | 性质 | 用途 |
|---|---|---|
| `resume-2col-zh.pdf` / `.html` | **本仓库自制夹具**：中文双栏合成简历 A4，Chrome 151（151.0.7922.140）print-to-pdf 产出 | T5（MYW-63）多栏 PDF 实测样本；T5R（MYW-66）「乱码必告警」回归夹具。其实测揭示了静默乱码缺陷：Chrome 打印用 **Type3 字体 + `/CIDToGIDMap /Identity`**（非 ObjStm，原始字节无任何既有 CID 特征），文本按 2 字节 GID 绘制且无本工具可解码的映射，提取输出为乱码——由 v0.1.1 防线二（输出侧乱码检测）命中告警 |
| `resume-objstm-constructed.pdf` | **本仓库脚本构造夹具**（`tests/make_objstm_fixture.py` 生成，确定性同字节）：Catalog/Pages/Page/Font(Type0+Identity-H)/FontDescriptor 全部压入 ObjStm，模拟新版 Word / WPS 导出的对象布局 | T5R 防线一回归夹具。本机无 WPS / 新版 Word 可导出真件，按 MYW-66 授权用脚本构造同构变体并在此注明 |
| `extraction-resume.json` | Chrome 夹具的提取输出存档（v0.1.0 时代，含「告警未触发」的缺陷现场） | 缺陷留证；v0.1.1 起同文件提取会触发 `cid_font_limited_support`（输出侧兜底） |
| `extraction-jos.json` | 真实期刊论文（软件学报 jos-7580，pdfTeX 管线）提取输出精简存档 | 正样本对照：原始字节 CID 特征命中告警的既有路径。因第三方版权，原文与其提取存档均不入库（未随公开仓库分发） |

重新生成构造夹具：

```bash
python3 tests/make_objstm_fixture.py   # 缺省覆盖写出 resume-objstm-constructed.pdf
```
