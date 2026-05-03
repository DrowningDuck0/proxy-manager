---
name: proxy-manager
description: "AI-assisted proxy management for WSL environments. Manages clash-meta proxy lifecycle, automatic speed testing for best node selection, and task-level proxy isolation. Use when a project requires external network access (pip install, git clone, curl downloads, huggingface). Covers the full workflow from proxy need detection to user approval to task execution."
---

# proxy-manager 工作流 skill

项目与代理管理的一体化工作流。定义了你、我和 proxy-manager 项目之间的完整协作流程。

## 前置条件

- proxy-manager 项目位于 `/mnt/i/openclawWS/proxy-manager/`
- clash-meta 内核（mihomo v1.19.24）和 geo 数据库已就位
- 订阅 URL 已配置（`config.yaml` 中 `subscription_url`）
- 依赖: `pip3 install PyYAML`

## 工作流程

### 阶段 1：需求分析流程

用户提出项目需求 → 按以下步骤执行：

1. **分析项目**，确定实现流程和技术方案
2. **检测代理需求**：分析哪些任务需要访问外网（如 pip 安装、git clone 海外仓库、curl 下载海外资源、访问 huggingface/github 等）
3. **列举代理任务清单**，包含：
   - 任务名
   - 需要代理的原因（为什么直连不行）
   - 预估执行时长
4. **请求用户统一审批**，用户批准/拒绝这些任务使用代理

### 阶段 2：任务执行流程

#### Step 2.1 — 启动 clash（如未运行）

用户批准后，检查 clash 是否运行：

- **clash 未运行** → 再次向用户确认启动 → `python3 proxy-manager.py start`
- **clash 已运行** → 跳过此步

#### Step 2.2 — 测速选优（每次都必须执行）

用户批准启动后，必须执行测速，**禁止跳过或假设已有缓存**：

**测速规则（二选一）：**

| 条件 | 操作 |
|------|------|
| 距上次测速 < 5 分钟 且 缓存中有记录 | `python3 proxy-manager.py speedtest`（快速模式） |
| 无缓存 或 距上次测速 ≥ 5 分钟 | `python3 proxy-manager.py speedtest --full`（全量测速） |

测速完成后等待节点切换生效（API 设置 `🚀 节点选择` 组 → 最快节点）。

#### Step 2.3 — 执行任务

按 skill 清单逐个执行代理任务：

```bash
python3 proxy-manager.py task "任务名" "要执行的命令"
```

- 每次 task 只能执行一个命令
- 多个 task 顺序执行，互不阻塞
- 某个 task 失败时，记录错误，**继续执行后续任务**（除非用户明确要求中止）

#### Step 2.4 — 后续处理

项目所有代理任务执行完毕后：

- 如果你还有后续的非代理步骤要处理，**先处理完，再回来问用户是否需要关闭代理**
- **不要自行 shutdown**，必须等用户表态

### 阶段 3：完成并清理

- 向用户汇报所有代理任务的执行结果（哪些成功、哪些失败）
- 询问是否需要关闭代理（`shutdown`）或保持运行

## 调用方式

```bash
cd /mnt/i/openclawWS/proxy-manager
python3 proxy-manager.py task "任务名" "命令"
```

示例：
```bash
python3 proxy-manager.py task "pip install" "pip install torch torchvision"
python3 proxy-manager.py task "clone model" "git clone https://huggingface.co/xxx"
```

注意：`task` 命令不会自动启动 clash，需要先 `start`。
如果 clash 未运行，`task` 会报错提示，不会自动启动。

## 可用指令

### 安装与配置

| 指令 | 说明 |
|------|------|
| `bash install.sh` | 一键安装：Python 依赖 + clash 核心验证 + AI Skill 部署 |
| `cp config.yaml.example config.yaml` | 创建配置文件 |
| `python3 proxy-manager.py url set <URL>` | 设置/更换订阅 URL（自动拉取配置并重启 clash） |
| `python3 proxy-manager.py url show` | 显示当前订阅 URL |

### 代理生命周期

| 指令 | 说明 |
|------|------|
| `python3 proxy-manager.py start` | 启动代理（常驻服务，自动部署后台 cooldown） |
| `python3 proxy-manager.py stop` | 停止代理 |
| `python3 proxy-manager.py cooldown` | 手动启动空闲关闭模式（30 秒无 task 自动停） |
| `python3 proxy-manager.py shutdown` | 立即关闭代理 + 停掉后台 cooldown |

### 管理与诊断

| 指令 | 说明 |
|------|------|
| `python3 proxy-manager.py status` | 查看代理状态与订阅健康状况 |
| `python3 proxy-manager.py test` | 联通测试（仅检测代理是否响应） |
| `python3 proxy-manager.py update` | 更新订阅配置（运行中自动重启 clash） |
| `python3 proxy-manager.py speedtest` | 自动测速，选最快节点（有缓存直接复用） |
| `python3 proxy-manager.py speedtest --full` | 强制全量重新测速 |
| `python3 proxy-manager.py task <name> <cmd>` | 在代理环境下执行命令（需先 start） |

### 完整示例：首次配置

```bash
cd /mnt/i/openclawWS/proxy-manager
bash install.sh
cp config.yaml.example config.yaml
# 编辑 config.yaml 填入订阅 URL
python3 proxy-manager.py url set "https://your-subscription-url"
python3 proxy-manager.py status
```

## 权限规则

| 操作 | 权限 |
|------|------|
| 读取配置、检测代理需求 | ✅ 自动执行 |
| 管理 clash 配置文件 | ✅ 自动执行 |
| 订阅更新 | ✅ 自动执行 |
| **启动 clash** | ❌ 必须问用户 |
| 测速选优 | ✅ 自动执行（批准后） |
| 在已运行的 clash 上执行 task | ✅ 自动执行 |
| 切换节点/模式 | ✅ 自动执行（测速后） |
| 后台 cooldown（由 start 自动部署） | ✅ 自动执行 |
| **立即关闭（shutdown）** | ❌ 必须问用户 |

每次启动 clash 前必须请求用户许可，提供：
- 为什么需要启动
- 预估执行时长
- 涉及的任务名

## 日志

所有操作记录在 `logs/task-YYYY-MM-DD.log`，包含：
- 任务名、执行时间
- 错误信息
- 执行结果（exit code）

## 注意事项

- WSL2 不支持 TUN 模式，只使用 HTTP/SOCKS5 代理模式
- 测速完成后 API 会设置 `🚀 节点选择`（或类似组名）到最快节点，等待几秒生效
- curl 测试时 stdout 过长会自动截断（超过 10 行或 2000 字节）
- 节点信息通过 clash RESTful API（localhost:9090）获取
- 所有节点类型已统一匹配（小写，包括 shadowsocks/vmess/trojan/hysteria2/vless/tuic 等）
- task 执行前会检测 clash 是否运行，未运行则报错
- 多个 task 之间互不阻塞，各自独立
- 执行项目时，先处理完所有非代理步骤（如果可能与后续代理任务冲突则例外），再统一提交代理任务清单并请求审批
- **代理任务的执行必须严格遵循本 skill 的工作流顺序，不得跳跃或省略步骤**
