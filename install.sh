#!/usr/bin/env bash
set -e

# proxy-manager 安装脚本
# 自动安装 Python 依赖并准备 clash 核心

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLASH_DIR="$PROJECT_DIR/clash"
MIMO_VERSION="v1.19.24"
MIMO_URL="https://github.com/MetaCubeX/mihomo/releases/download/${MIMO_VERSION}/mihomo-linux-amd64-${MIMO_VERSION}.gz"

echo "📦 安装 Python 依赖..."
pip3 install -r "$PROJECT_DIR/requirements.txt" --quiet

if [ -f "$CLASH_DIR/mihomo" ] && [ -x "$CLASH_DIR/mihomo" ]; then
    echo "✅ clash 核心已就绪"
else
    echo "📥 下载 clash-meta 核心..."
    mkdir -p "$CLASH_DIR"
    curl -sL "$MIMO_URL" -o /tmp/mihomo.gz
    gunzip -f /tmp/mihomo.gz
    mv /tmp/mihomo "$CLASH_DIR/mihomo"
    chmod +x "$CLASH_DIR/mihomo"
    echo "✅ clash 核心已安装"
fi

echo ""
echo "🎉 安装完成！"
echo "下一步: 设置订阅 URL → python3 proxy-manager.py url set '你的订阅链接'"
