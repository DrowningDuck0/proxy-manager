#!/usr/bin/env bash
set -e

# proxy-manager 安装脚本
# 检查 Python 依赖，验证 clash 核心就绪

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLASH_DIR="$PROJECT_DIR/clash"

echo "📦 检查 Python 依赖..."
# proxy-manager 仅依赖 PyYAML，多数系统已自带
MISSING=""
python3 -c "import yaml" 2>/dev/null || MISSING="yaml"

if [ -n "$MISSING" ]; then
    echo "  缺少 PyYAML，尝试安装..."
    pip3 install -r "$PROJECT_DIR/requirements.txt" --quiet --break-system-packages 2>/dev/null || \
    pip3 install -r "$PROJECT_DIR/requirements.txt" --quiet 2>/dev/null || \
    sudo apt install -y python3-yaml 2>/dev/null || \
    echo "  ⚠️  无法自动安装 PyYAML，请手动运行: pip3 install PyYAML"
else
    echo "  ✅ PyYAML 已就绪"
fi

if [ -f "$CLASH_DIR/mihomo" ] && [ -x "$CLASH_DIR/mihomo" ]; then
    echo "✅ clash 核心已就绪"
else
    echo "  ❌ clash/mihomo 不存在，请确认 git clone 完整"
    echo "  或从 https://github.com/DrowningDuck0/proxy-manager/releases 下载后放到:"
    echo "  $CLASH_DIR/mihomo"
    exit 1
fi

echo ""
echo "🎉 安装完成！"
echo "下一步:"
echo "  1. cp config.yaml.example config.yaml"
echo "  2. 编辑 config.yaml 填入订阅 URL"
echo "  3. python3 proxy-manager.py status"
