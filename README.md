# proxy-manager

WSL 环境下智能代理任务管理器。随用随开，用完即关。

## 快速开始

### 1. 配置订阅 URL

```bash
python3 proxy-manager.py url set "你的clash机场订阅链接"
```

### 2. 查看状态

```bash
python3 proxy-manager.py status
```

### 3. 执行需要代理的任务

```bash
python3 proxy-manager.py task "下载模型" "curl -Lo model.bin https://huggingface.co/xxx"
```

## 指令一览

| 指令 | 说明 |
|------|------|
| `status` | 查看代理状态与订阅健康 |
| `url show` | 显示当前订阅 URL |
| `url set <URL>` | 设置/更换订阅 URL |
| `update` | 更新订阅配置 |
| `start` | 手动启动代理 |
| `stop` | 手动停止代理 |
| `test` | 联通测试 |
| `speedtest` | 自动测速所有节点，选最快节点 |
| `task <name> <cmd>` | 执行代理任务（自动测速选优 → 执行 → 关闭） |

详见 [docs/COMMANDS.md](docs/COMMANDS.md)

## 项目结构

```
proxy-manager/
├── proxy-manager.py    # 主程序
├── config.yaml          # 配置
├── clash/
│   ├── mihomo           # clash-meta 内核
│   └── config.yaml      # clash 配置（订阅生成）
├── docs/
│   └── COMMANDS.md      # 指令文档
└── README.md
```
