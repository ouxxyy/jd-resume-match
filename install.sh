#!/bin/sh
# jd-resume-match skill 安装脚本（POSIX sh，零依赖）
# 只写入 <目标>/jd-resume-match/ 一个目录；目标已存在同名非空目录时拒绝（不覆盖用户已有文件）。
# 用法: ./install.sh [目标skills目录] [--force]
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET=""
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -h|--help) echo "用法: $0 [目标skills目录] [--force]  （默认目标: \$HOME/.claude/skills）"; exit 0 ;;
    *) if [ -z "$TARGET" ]; then TARGET="$arg"; else echo "错误: 多余参数 $arg" >&2; exit 2; fi ;;
  esac
done
TARGET="${TARGET:-$HOME/.claude/skills}"

# 兼容两种布局：本仓库根（SKILL.md 在当前目录）/ 压缩包解压目录（SKILL.md 在 jd-resume-match/ 子目录）
if [ -f "$HERE/SKILL.md" ]; then
  SRC="$HERE"
elif [ -f "$HERE/jd-resume-match/SKILL.md" ]; then
  SRC="$HERE/jd-resume-match"
else
  echo "错误: 在 $HERE 找不到 SKILL.md，请在仓库根目录或解压后的包目录内运行。" >&2
  exit 1
fi
command -v python3 >/dev/null 2>&1 || { echo "错误: 需要 python3（3.9+，仅标准库）。" >&2; exit 1; }

DEST="$TARGET/jd-resume-match"
if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
  if [ "$FORCE" = "1" ]; then
    echo "⚠ --force：将覆盖已有目录 $DEST"
  else
    echo "拒绝安装：$DEST 已存在且非空。未覆盖任何文件。"
    echo "确认要替换时加 --force；或先手动移走旧目录。"
    exit 1
  fi
fi

mkdir -p "$TARGET"
rm -rf "$DEST.tmp-install"
cp -R "$SRC" "$DEST.tmp-install"
if [ -e "$DEST" ]; then rm -rf "$DEST"; fi
mv "$DEST.tmp-install" "$DEST"

echo "已安装: $DEST"
echo "冒烟验证（结构+引用+隐私校验，只读本地文件）:"
if python3 "$DEST/scripts/validate_report.py" --input "$DEST/examples/case-b-2yr-data-dev/expected.json"; then
  echo "安装完成。对智能体说「用 jd-resume-match 分析简历+JD」即可使用。"
else
  echo "警告: 冒烟验证未通过，请检查 python3 版本（需 3.9+）后重试。" >&2
  exit 1
fi
