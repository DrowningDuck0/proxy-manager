# proxy-manager

WSL 环境下智能代理任务管理器。随用随开，用完即关，任务级隔离。

## 前置条件

- WSL 2（Ubuntu/Debian 等 Linux 发行版）
- Python 3.8+
- pip3

## 安装

```bash
# 1. 克隆仓库
cd /mnt/i/openclawWS && rm -rf proxy-manager && git clone https://github.com/DrowningDuck0/proxy-manager.git
cd proxy-manager

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 配置订阅 URL
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入你的订阅 URL

# 4. 查看状态
python3 proxy-manager.py status
```

> 💡 clash 核心（mihomo 二进制）已包含在仓库中，clone 后即可使用，无需额外下载。

### 配置

```bash
cp config.yaml.example config.yaml
```

然后编辑 `config.yaml`，填入订阅 URL。
配置项说明见 [docs/COMMANDS.md](docs/COMMANDS.md)。

### 从备份恢复（可选）

`/mnt/i/openclawWS/proxy-manager-backup/proxy-manager-full-backup-v2.0.tar.gz` 包含完整项目 + clash 核心。

```bash
cd /mnt/i/openclawWS
tar xzf proxy-manager-backup/proxy-manager-full-backup-v2.0.tar.gz
cd proxy-manager
```

## 使用

```bash
# 执行需要代理的任务（自动测速选优 → 执行 → 延迟关闭）
python3 proxy-manager.py task "pip install torch" "pip install torch torchvision"
python3 proxy-manager.py task "clone model" "git clone https://huggingface.co/xxx"

# 查看状态
python3 proxy-manager.py status

# 手动控制
python3 proxy-manager.py start      # 启动代理
python3 proxy-manager.py stop       # 停止代理
python3 proxy-manager.py shutdown   # 立即关闭代理 + 停掉后台 cooldown
```

## 指令一览

| 指令 | 说明 |
|------|------|
| `status` | 查看代理状态、订阅健康、联通测试 |
| `url show` | 显示当前订阅 URL |
| `url set <URL>` | 设置/更换订阅 URL |
| `update` | 更新订阅配置 |
| `start` | 手动启动代理 |
| `stop` | 手动停止代理 |
| `test` | 联通测试 |
| `speedtest [--full]` | 测速（缓存/全量），自动选最快节点 |
| `task [--full] <name> <cmd>` | 执行代理任务（自动测速 → 执行 → 延迟关闭） |
| `shutdown` | 立即关闭代理 + 停掉后台 cooldown |

详见 [docs/COMMANDS.md](docs/COMMANDS.md)

## 功能特性

- ✅ **智能测速** — 自动测试所有节点，选延迟最低的
- ✅ **测速缓存** — 5 分钟内复用缓存，不浪费流量
- ✅ **冲突保护** — 并发任务自动排队等待
- ✅ **延迟关闭** — 任务完成 30 秒无活动自动关闭，连续任务不掉线
- ✅ **日志记录** — 所有操作写入 `logs/` 目录，方便回溯
- ✅ **隐私保护** — 订阅 URL 仅存本地，不上传 GitHub

## 项目结构

```
proxy-manager/
├── proxy-manager.py    # 主程序
├── config.yaml          # 配置（本地，已 .gitignore）
├── config.yaml.example  # 配置示例
├── requirements.txt     # Python 依赖
├── install.sh           # 安装脚本
├── clash/
│   ├── mihomo           # clash-meta 内核
│   └── config.yaml      # clash 配置
├── docs/
│   └── COMMANDS.md      # 完整指令文档
└── README.md
```
