#!/usr/bin/env bash
set -e

# proxy-manager 安装脚本
# 自动准备 Python 依赖并下载 clash 核心

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLASH_DIR="$PROJECT_DIR/clash"
MIMO_VERSION="v1.19.24"
MIMO_URL="https://github.com/MetaCubeX/mihomo/releases/download/${MIMO_VERSION}/mihomo-linux-amd64-${MIMO_VERSION}.gz"

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
    echo "📥 下载 clash-meta 核心..."
    mkdir -p "$CLASH_DIR"
    if curl -sL --connect-timeout 10 "$MIMO_URL" -o /tmp/mihomo.gz 2>/dev/null && [ -s /tmp/mihomo.gz ]; then
        gunzip -f /tmp/mihomo.gz
        mv /tmp/mihomo "$CLASH_DIR/mihomo"
        chmod +x "$CLASH_DIR/mihomo"
        echo "✅ clash 核心已安装"
    else
        echo "  ❌ 下载失败（可能需要代理或手动下载）"
        echo "  请手动下载后放到: $CLASH_DIR/mihomo"
        echo "  下载地址: https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.24"
        rm -f /tmp/mihomo.gz
    fi
fi

echo ""
echo "🎉 安装完成！"
echo "下一步:"
echo "  1. cp config.yaml.example config.yaml"
echo "  2. 编辑 config.yaml 填入订阅 URL"
echo "  3. python3 proxy-manager.py status"
