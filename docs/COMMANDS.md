# proxy-manager 指令文档

## 概述

proxy-manager 是一个 WSL 环境下的智能代理任务管理器。核心逻辑：

- **随用随开，用完即关** — 只在需要代理的任务执行时启动 clash，完成后立即关闭
- **按进程隔离** — 代理环境变量仅作用于当前任务，不影响系统和其他进程
- **每次启用前联通测试** — 确保网络可用再执行任务
- **统一批准机制** — 项目涉及代理的任务需经用户批准

---

## 基础指令

### 查看代理状态与订阅健康状况

```
python3 proxy-manager.py status
```

输出示例：

```
代理状态: 🔴 已停止
订阅: ✅ 已配置
订阅 URL: https://xxx.com/sub
联通状态: 🟢 联通成功，延迟 120ms
```

### 查看当前订阅 URL

```
python3 proxy-manager.py url show
```

### 设置/更换订阅 URL

```
python3 proxy-manager.py url set <新的订阅URL>
```

设置后会自动拉取订阅并解析节点。

### 手动更新订阅配置

```
python3 proxy-manager.py update
```

如果订阅 URL 未配置，会提示先设置。

---

## 手动操作

### 启动代理

```
python3 proxy-manager.py start
```

启动后自动进行联通测试并报告延迟。

### 停止代理

```
python3 proxy-manager.py stop
```

### 联通测试

```
python3 proxy-manager.py test
```

测试代理是否正常工作，返回延迟毫秒数。

### 自动测速选优

```
python3 proxy-manager.py speedtest
```

对所有节点进行延迟测试，选出最快的节点并设置为默认。

输出示例：

```
┌─ ⏱ 自动测速选优 ──────────────────────────
│ 代理已启动
│ 节点数: 44，正在测速...
│ 进度: 44/44 | 可用: 33 个
│ 最快 Top5:
│   ⚡ 🇯🇵 日本 - 04✦高级 -: 67ms
│   ⚡ 🇯🇵 日本 - 01✦高级 -: 83ms
│   ⚡ 🇯🇵 日本 - 05✦高级 -: 85ms
│ ⚡ 最优: 🇯🇵 日本 - 04✦高级 - (67ms)
│ 测试: 33/44 个节点可用
└─ ✅ 测速完成
```

---

## 代理任务（核心功能）

### 执行需要代理的任务

```
python3 proxy-manager.py task "<任务名>" "<命令>"
```

示例：

```bash
# pip 安装需要代理的包
python3 proxy-manager.py task "pip install torch" "pip install torch torchvision"

# git clone 海外仓库
python3 proxy-manager.py task "clone huggingface" "git clone https://huggingface.co/mistralai/Mistral-7B-v0.1"

# curl 海外资源
python3 proxy-manager.py task "download model" "curl -Lo model.bin https://example.com/model.bin"
```

执行流程（自动包含测速选优）：

```
┌─ 🔒 开启代理
├─ ⏱ 测速选优
│   节点数: 44，正在测速...
│   进度: 44/44 | 可用: 33 个
│   最快 Top5:
│     ⚡ 🇯🇵 日本 - 04✦高级 -: 67ms
│   ✅ 最快节点: 🇯🇵 日本 - 04✦高级 - (67ms)，已设为默认
├─ 🔍 联通测试
│   ✅ 延迟: 67ms
├─ 📦 执行: pip install torch
│   returncode: 0
│   ✅ 任务执行成功
├─ 🔒 关闭代理
└─ ✅ 任务完成
```

如果任务失败（非零返回），会返回错误码。

---

## 更新 README

---

## 帮助

```
python3 proxy-manager.py help
```

显示指令汇总。

---

## 工作流程（用户视角）

1. **项目经理阶段：** 提出项目需求
2. **我分析需要代理的任务**，列出清单请求批准
3. **你统一批准**允许使用代理的任务列表
4. **执行阶段：** 遇到代理任务时自动封装执行
5. **每次执行：** 启动代理 → 联通测试 → 执行 → 关闭
6. **如果代理连通失败：** 报告错误，等待指示
