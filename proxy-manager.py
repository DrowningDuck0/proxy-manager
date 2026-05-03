#!/usr/bin/env python3
"""
proxy-manager — 智能代理任务管理器
WSL 环境下按需启动 clash，随用随开，用完即关。
"""

import os
import sys
import subprocess
import time
import json
import yaml
import urllib.request
import urllib.parse
import socket
import shlex
import http.client
import base64
import fcntl
import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.yaml")
CLASH_DIR = os.path.join(PROJECT_DIR, "clash")
SPEED_CACHE_PATH = os.path.join(PROJECT_DIR, "speed_cache.json")
SPEED_CACHE_TTL = 300  # 缓存有效期 5 分钟
# 文件锁目录（用于并行时的缓存竞态保护）
LOCK_DIR = os.path.join(PROJECT_DIR, ".locks")
# 日志目录
LOG_DIR = os.path.join(PROJECT_DIR, "logs")

class ProxyManager:
    """代理管理器核心"""

    def __init__(self):
        os.chdir(PROJECT_DIR)  # 始终确保 CWD 是项目目录
        self.config = self._load_config()
        self.clash_binary = os.path.join(PROJECT_DIR, self.config.get("clash_binary", "./clash/mihomo"))
        self.proxy_port = self.config.get("proxy_port", 7890)
        self.api_port = self.config.get("api_port", 9090)
        self.clash_process = None

    def _load_config(self):
        """加载配置"""
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                return yaml.safe_load(f) or {}
        return {}

    def _save_config(self):
        """保存配置（原子写入）"""
        tmp_path = CONFIG_PATH + ".tmp"
        with open(tmp_path, 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_PATH)

    def has_subscription(self):
        """检查是否配置了订阅 URL"""
        url = self.config.get("subscription_url", "")
        return bool(url and url.strip())

    def set_subscription(self, url):
        """设置订阅 URL"""
        self.config["subscription_url"] = url.strip()
        self._save_config()

    def get_subscription(self):
        """获取当前订阅 URL"""
        return self.config.get("subscription_url", "")

    def _is_yaml_text(self, raw):
        """判断原始字节是否为 YAML 文本（而非 base64）"""
        try:
            text = raw.decode('utf-8').strip()
            # YAML 通常以这几个特征开头
            return text.startswith(('#', 'port:', 'mixed-port:', 'proxies:', 'mode:', 'socks-port:',
                                    'redir-port:', 'tproxy-port:', 'external-controller:',
                                    'allow-lan:', 'log-level:', 'ipv6:', 'tun:', 'dns:',
                                    'rules:', 'proxy-groups:', 'proxy-providers:',
                                    'rule-providers:', 'secret:', 'profile:', '{'))
        except Exception:
            return False

    def _atomic_write_clash_config(self, config_data):
        """原子写入 clash 配置文件（临时文件 + rename 确保写入安全）"""
        clash_config_path = os.path.join(CLASH_DIR, "config.yaml")
        tmp_path = clash_config_path + ".tmp"
        with open(tmp_path, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, clash_config_path)
        return clash_config_path

    def update_subscription(self):
        """更新订阅配置 — 从 URL 拉取最新配置并写入 clash 配置"""
        url = self.get_subscription()
        if not url:
            return {"success": False, "error": "未配置订阅 URL"}

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()

            # 先判断是 base64 编码还是纯 YAML
            if self._is_yaml_text(raw):
                config_data = yaml.safe_load(raw.decode('utf-8'))
            else:
                # 尝试 base64 解码
                try:
                    decoded = base64.b64decode(raw).decode('utf-8')
                    config_data = yaml.safe_load(decoded)
                except Exception:
                    config_data = yaml.safe_load(raw.decode('utf-8'))

            if not config_data or not isinstance(config_data, dict):
                return {"success": False, "error": "订阅内容解析失败"}

            # 强制注入代理端口设置（覆盖订阅中的值，确保 start() 能正确检测）
            config_data["mixed-port"] = self.proxy_port
            config_data["external-controller"] = f"127.0.0.1:{self.api_port}"
            # DNS 避免绑定 53 端口（防止 WSL systemd-resolved 冲突）
            if "dns" in config_data and isinstance(config_data["dns"], dict):
                config_data["dns"].pop("listen", None)

            self._atomic_write_clash_config(config_data)

            # 提取节点信息
            proxies = config_data.get("proxies", [])
            proxy_names = [p.get("name", "unknown") for p in proxies]

            return {
                "success": True,
                "node_count": len(proxies),
                "nodes": proxy_names[:20],  # 只显示前20个
                "message": f"订阅更新成功，获取到 {len(proxies)} 个节点"
            }

        except Exception as e:
            return {"success": False, "error": f"订阅更新失败: {str(e)}"}

    def _generate_clash_config(self):
        """当没有订阅时生成一个基础测试配置"""
        config = {
            "mixed-port": self.proxy_port,
            "external-controller": f"127.0.0.1:{self.api_port}",
            "mode": "rule",
            "log-level": "warning",
            "dns": {
                "enabled": True,
                "nameserver": ["223.5.5.5", "114.114.114.114", "8.8.8.8"]
            },
            "proxies": [],
            "proxy-groups": [],
            "rules": []
        }
        return self._atomic_write_clash_config(config)

    def _ensure_geo_files(self):
        """确保 geo 数据库文件存在（支持 CDN fallback）"""
        geoip = os.path.join(CLASH_DIR, "geoip.metadb")
        geosite = os.path.join(CLASH_DIR, "GeoSite.dat")
        # 主源 + jsdelivr CDN fallback（GitHub 直连可能被墙）
        urls_for = {
            "geoip.metadb": [
                "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb",
                "https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb",
            ],
            "GeoSite.dat": [
                "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat",
                "https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geosite.dat",
            ],
        }

        for path, name in [(geoip, "geoip.metadb"), (geosite, "GeoSite.dat")]:
            if os.path.exists(path) and os.path.getsize(path) >= 1000:
                continue
            print(f"├─ 下载 {name}...")
            success = False
            for url in urls_for[name]:
                try:
                    urllib.request.urlretrieve(url, path)
                    if os.path.exists(path) and os.path.getsize(path) >= 1000:
                        success = True
                        break
                    print(f"│  ⚠️ 从 {url} 下载文件过小，尝试备用源")
                except Exception as e:
                    print(f"│  ⚠️ {url} 失败: {e}")
            if not success:
                return {"success": False, "error": f"下载 {name} 失败（所有源均不可用）"}
        return {"success": True}

    def start(self):
        """启动 clash 代理（常驻服务），启动后自动部署 cooldown 后台进程"""
        if self.is_running():
            return {"success": True, "message": "代理已在运行中"}

        # 检查是否有订阅配置，否则启动空壳无意义
        if not self.has_subscription():
            return {"success": False, "message": "未配置订阅 URL，无法启动代理。请先设置订阅: python3 proxy-manager.py url set <URL>"}

        # 确保有配置文件
        clash_config = os.path.join(CLASH_DIR, "config.yaml")
        if not os.path.exists(clash_config):
            self.update_subscription()

        # 确保 geo 文件
        geo_result = self._ensure_geo_files()
        if not geo_result["success"]:
            return geo_result

        try:
            self.clash_process = subprocess.Popen(
                [self.clash_binary, "-d", CLASH_DIR, "-f", clash_config],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # 等待代理就绪（延长时间到 30 次 × 0.5s = 15s）
            for i in range(30):
                if self._check_port(self.proxy_port):
                    # 启动 cooldown 后台进程（自动管理空闲关闭）
                    try:
                        self._start_cooldown_daemon()
                    except Exception as ce:
                        pass
                    return {"success": True, "message": "代理已启动"}
                time.sleep(0.5)

            # 启动超时
            self.stop()
            return {"success": False, "message": "代理启动超时（可能需手动检查配置）"}

        except Exception as e:
            return {"success": False, "message": f"启动失败: {str(e)}"}

    def _start_cooldown_daemon(self):
        """启动后台 cooldown 进程（先杀掉旧进程）"""
        cooldown_pidfile = os.path.join(LOCK_DIR, "cooldown.pid")
        # 确保锁目录存在
        os.makedirs(LOCK_DIR, exist_ok=True)
        self._kill_process_by_pidfile(cooldown_pidfile)

        cooldown_proc = subprocess.Popen(
            [sys.executable, os.path.join(PROJECT_DIR, "proxy-manager.py"), "cooldown"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        with open(cooldown_pidfile, "w") as f:
            f.write(str(cooldown_proc.pid))

    def stop(self):
        """关闭 clash 代理
        优先杀自己启动的进程；如果 clash_process 为空（例如从 cooldown 进程调用），
        则搜索 clash 二进制进程名杀掉
        """
        killed = False
        if self.clash_process:
            try:
                self.clash_process.terminate()
                self.clash_process.wait(timeout=5)
                killed = True
            except Exception:
                try:
                    self.clash_process.kill()
                    killed = True
                except Exception:
                    pass
            self.clash_process = None

        if not killed:
            # Fallback: 搜索 clash 二进制进程
            try:
                result = subprocess.run(
                    ["pgrep", "-f", os.path.basename(self.clash_binary)],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    pids = [p.strip() for p in result.stdout.split() if p.strip()]
                    for pid in pids:
                        try:
                            os.kill(int(pid), 15)  # SIGTERM
                        except Exception:
                            pass
                    killed = True
            except Exception:
                pass

        if killed:
            return {"success": True, "message": "代理已关闭"}
        return {"success": True, "message": "代理未运行"}

    def is_running(self):
        """检查代理是否在运行"""
        return self._check_port(self.proxy_port)

    def _check_port(self, port, host="127.0.0.1"):
        """检查端口是否开放"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _api_request(self, method, path, data=None):
        """通过 clash RESTful API 发送请求（支持可选鉴权）"""
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.api_port, timeout=5)
            body = json.dumps(data).encode('utf-8') if data else None
            headers = {"Content-Type": "application/json"}
            # 支持 Clash API 鉴权（如果配置了 secret）
            secret = self.config.get("secret", "")
            if secret:
                headers["Authorization"] = f"Bearer {secret}"
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            resp_data = resp.read().decode('utf-8')
            conn.close()
            if resp.status == 200 and resp_data:
                return json.loads(resp_data)
            return None
        except Exception:
            return None

    def get_all_proxies(self):
        """获取所有代理节点列表"""
        data = self._api_request("GET", "/proxies")
        if not data:
            return []
        proxies = data.get("proxies", {})
        # 只获取实际节点（排除 proxy-groups 和特殊名字）
        exclude_names = {"DIRECT", "REJECT", "PASS", "COMPATIBLE"}
        # 实际的代理节点类型（全转小写比较）
        proxy_types = {'shadowsocks', 'vmess', 'trojan', 'hysteria2', 'vless', 'tuic', 'socks5', 'http', 'ss', 'ssr'}
        nodes = []
        for name, info in proxies.items():
            ptype = (info.get("type") or "").lower()
            if ptype in proxy_types:
                if name not in exclude_names and not name.startswith("["):
                    nodes.append(name)
        return nodes

    def get_select_groups(self):
        """获取用户可选的选择组（type: select）"""
        data = self._api_request("GET", "/proxies")
        if not data:
            return []
        proxies = data.get("proxies", {})
        groups = []
        for name, info in proxies.items():
            if info.get("type") == "Select":
                groups.append(name)
        return groups

    def test_proxy_delay(self, proxy_name, test_url="https://www.gstatic.com/generate_204", timeout=5000):
        """测试单个代理节点延迟"""
        params = urllib.parse.urlencode({"url": test_url, "timeout": str(timeout)})
        path = f"/proxies/{urllib.parse.quote(proxy_name, safe='')}/delay?{params}"
        result = self._api_request("GET", path)
        if result and "delay" in result:
            return result["delay"]
        return None

    def _acquire_file_lock(self, lock_name, timeout=5):
        """获取文件锁（防止并行进程竞态，最多等 timeout 秒）"""
        os.makedirs(LOCK_DIR, exist_ok=True)
        lock_path = os.path.join(LOCK_DIR, lock_name)
        fd = None
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return fd  # 拿到锁
                except (IOError, OSError):
                    time.sleep(0.1)
            # 超时，放弃
            os.close(fd)
            return None
        except Exception:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
            return None

    def _release_file_lock(self, fd):
        """释放文件锁"""
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(fd)
            except Exception:
                pass

    def _increment_task_count(self):
        """递增 task 引用计数，表示启动了一个 task"""
        os.makedirs(LOCK_DIR, exist_ok=True)
        count_path = os.path.join(LOCK_DIR, "task_count")
        lock_fd = self._acquire_file_lock("task_count.lock", timeout=5)
        try:
            count = 0
            if os.path.exists(count_path):
                try:
                    with open(count_path) as f:
                        count = int(f.read().strip() or "0")
                except Exception:
                    count = 0
            count += 1
            with open(count_path, 'w') as f:
                f.write(str(count))
            return count
        finally:
            if lock_fd is not None:
                self._release_file_lock(lock_fd)

    def _decrement_task_count(self):
        """递减 task 引用计数，表示 task 结束"""
        os.makedirs(LOCK_DIR, exist_ok=True)
        count_path = os.path.join(LOCK_DIR, "task_count")
        lock_fd = self._acquire_file_lock("task_count.lock", timeout=5)
        try:
            count = 0
            if os.path.exists(count_path):
                try:
                    with open(count_path) as f:
                        count = int(f.read().strip() or "0")
                except Exception:
                    count = 0
            count = max(0, count - 1)
            with open(count_path, 'w') as f:
                f.write(str(count))
            return count
        finally:
            if lock_fd is not None:
                self._release_file_lock(lock_fd)

    def _get_task_count(self):
        """读取当前 task 引用计数"""
        count_path = os.path.join(LOCK_DIR, "task_count")
        if not os.path.exists(count_path):
            return 0
        try:
            with open(count_path) as f:
                return int(f.read().strip() or "0")
        except Exception:
            return 0

    def _get_log_path(self):
        """获取今天的日志文件路径"""
        os.makedirs(LOG_DIR, exist_ok=True)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        return os.path.join(LOG_DIR, f"task-{today}.log")

    def _log(self, message, log_type="STATUS"):
        """同时输出到终端和日志文件（tee 效果）"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {log_type}: {message}"
        print(log_line)
        try:
            log_path = self._get_log_path()
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
                f.flush()
        except Exception:
            pass

    def _read_lock_pid(self, lock_path):
        """读取锁文件中的 PID"""
        try:
            with open(lock_path) as f:
                return f.read().strip()
        except Exception:
            return None

    def _kill_process_by_pidfile(self, pidfile_path, sig=15):
        """根据 PID 文件杀掉进程"""
        pid = self._read_lock_pid(pidfile_path)
        if pid and pid.isdigit():
            try:
                os.kill(int(pid), sig)
                return True
            except ProcessLookupError:
                return True
            except Exception:
                pass
        return False

    def _load_speed_cache(self):
        """加载测速缓存"""
        if not os.path.exists(SPEED_CACHE_PATH):
            return None
        try:
            with open(SPEED_CACHE_PATH) as f:
                cache = json.load(f)
            if time.time() - cache.get("timestamp", 0) < SPEED_CACHE_TTL:
                return cache
        except Exception:
            pass
        return None

    def _save_speed_cache(self, fastest_name, fastest_latency, all_results, node_count):
        """保存测速缓存（带文件锁防并行竞态）"""
        lock_fd = self._acquire_file_lock("speed_cache.lock")
        try:
            cache = {
                "timestamp": time.time(),
                "fastest": fastest_name,
                "fastest_latency": fastest_latency,
                "top5": [{"name": n, "latency": d} for n, d in all_results[:5]],
                "total_tested": len(all_results),
                "total_nodes": node_count
            }
            with open(SPEED_CACHE_PATH, 'w') as f:
                json.dump(cache, f)
        finally:
            self._release_file_lock(lock_fd)

    def select_fastest_node(self, quick_mode=False):
        """自动测速所有节点，选出最快的并设为默认
        quick_mode: True 时使用缓存（5分钟内有效），否则全量测速
        """
        if not self.is_running():
            return {"success": False, "message": "代理未运行"}

        # 快速模式：检查缓存
        if quick_mode:
            cache = self._load_speed_cache()
            if cache:
                print(f"│ 使用缓存: {cache['fastest']} ({cache['fastest_latency']}ms) 来自 {int(time.time()-cache['timestamp'])}秒前")
                fastest_name = cache['fastest']
                fastest_delay = cache['fastest_latency']
                # 仍然设到选择组
                self._set_fastest_to_groups(fastest_name)
                return {
                    "success": True, "fastest": fastest_name, "fastest_latency": fastest_delay,
                    "tested": cache['total_tested'], "total": cache['total_nodes'], "cached": True,
                    "message": f"最快节点: {fastest_name} ({fastest_delay}ms)"
                }
            else:
                print(f"│ 缓存过期或无缓存，重新测速")

        nodes = self.get_all_proxies()
        if not nodes:
            return {"success": False, "message": "未找到可用节点"}

        print(f"│ 节点数: {len(nodes)}，正在测速...")

        results = []
        for i, name in enumerate(nodes):
            delay = self.test_proxy_delay(name, timeout=3000)
            if delay is not None and delay > 0:
                results.append((name, delay))
            if (i + 1) % 10 == 0 or i == len(nodes) - 1:
                print(f"│ 进度: {i+1}/{len(nodes)} | 可用: {len(results)} 个")

        if not results:
            return {"success": False, "message": "所有节点均超时"}

        results.sort(key=lambda x: x[1])
        fastest_name, fastest_delay = results[0]

        top5 = results[:5]
        print(f"│ 最快 Top5:")
        for n, d in top5:
            print(f"│   ⚡ {n}: {d}ms")

        # 保存缓存
        self._save_speed_cache(fastest_name, fastest_delay, results, len(nodes))

        # 设置到选择组
        self._set_fastest_to_groups(fastest_name)

        return {
            "success": True, "fastest": fastest_name, "fastest_latency": fastest_delay,
            "tested": len(results), "total": len(nodes), "cached": False,
            "message": f"最快节点: {fastest_name} ({fastest_delay}ms)"
        }

    def _set_fastest_to_groups(self, fastest_name):
        """将最快节点设置到所有可用的 Selector 选择组"""
        select_groups = self.get_select_groups()
        main_group = None
        for group in select_groups:
            if "节点选择" in group or "自动选择" in group:
                main_group = group
                break
        if not main_group and select_groups:
            main_group = select_groups[0]

        if main_group:
            # 检查该组是否允许设置（只有 Selector 类型的组才接受 PUT）
            data = self._api_request("GET", "/proxies")
            if data:
                proxies = data.get("proxies", {})
                group_info = proxies.get(main_group, {})
                if group_info.get("type") == "Selector" and fastest_name in group_info.get("all", []):
                    path = f"/proxies/{urllib.parse.quote(main_group, safe='')}"
                    self._api_request("PUT", path, data={"name": fastest_name})
                    print(f"│ ✅ 已设置 '{main_group}' → {fastest_name}")

    def _health_check_url(self, test_url, timeout):
        """对单个 URL 执行联通测试"""
        proxy_handler = urllib.request.ProxyHandler({
            "http": f"http://127.0.0.1:{self.proxy_port}",
            "https": f"http://127.0.0.1:{self.proxy_port}"
        })
        opener = urllib.request.build_opener(proxy_handler)
        # 设置合适的 User-Agent 避免某些 CDN 拦截
        opener.addheaders = [('User-Agent', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36')]
        try:
            start = time.time()
            with opener.open(test_url, timeout=timeout) as resp:
                latency = int((time.time() - start) * 1000)
                return {
                    "success": True,
                    "latency_ms": latency,
                    "status_code": resp.status,
                    "message": f"联通成功，延迟 {latency}ms"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"联通测试失败: {str(e)}",
                "latency_ms": None,
                "url": test_url
            }

    def health_check(self):
        """联通测试 — 多 URL fallback"""
        if not self.is_running():
            return {"success": False, "error": "代理未运行", "latency_ms": None, "skipped": True}

        test_urls = self.config.get("health_check", {}).get("test_urls", [])
        if not test_urls:
            default = self.config.get("health_check", {}).get("test_url", "https://www.google.com")
            test_urls = [default, "https://www.gstatic.com/generate_204", "https://www.youtube.com"]

        timeout = self.config.get("health_check", {}).get("timeout_seconds", 5)
        errors = []

        for url in test_urls:
            result = self._health_check_url(url, timeout)
            if result["success"]:
                return result
            errors.append(result.get("error", "unknown"))

        return {
            "success": False,
            "error": f"所有测试点均失败: {'; '.join(errors)}",
            "latency_ms": None
        }

    def task_wrapper(self, task_name, command, env_extras=None):
        """
        代理任务封装器 — 只设置环境变量，执行命令，不操作 clash 生命周期。
        clash 需已运行（由 start 命令管理）。
        """
        result = {
            "task": task_name,
            "status": "failed",
            "stdout": "",
            "stderr": "",
        }

        # 0. 检查 clash 是否在运行
        if not self.is_running():
            self._log(f"TASK: 代理未运行，拒绝执行", "ERROR")
            print(f"❌ 代理未运行，请先执行 `python3 proxy-manager.py start`")
            result["error"] = "代理未运行"
            return result

        # 1. 递增引用计数
        self._log(f"TASK: {task_name}", "TASK")
        count = self._increment_task_count()
        print(f"┌─ 📦 执行: {task_name} (active tasks: {count}) ──────")

        try:
            # 2. 设置代理环境变量并执行命令
            env = os.environ.copy()
            env["http_proxy"] = f"http://127.0.0.1:{self.proxy_port}"
            env["https_proxy"] = f"http://127.0.0.1:{self.proxy_port}"
            env["all_proxy"] = f"socks5://127.0.0.1:{self.proxy_port}"
            env["no_proxy"] = "localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.cn"

            if env_extras:
                env.update(env_extras)

            proc = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=600  # 10分钟超时
            )
            result["stdout"] = proc.stdout
            result["stderr"] = proc.stderr
            result["returncode"] = proc.returncode
            print(f"│ returncode: {proc.returncode}")

            if proc.stdout:
                lines = proc.stdout.strip().split('\n')
                if len(lines) > 10 or len(proc.stdout) > 2000:
                    print(f"│ (输出过长，截取尾部 {min(len(lines),10)} 行，共 {len(lines)} 行/{len(proc.stdout)} 字节)")
                    for line in lines[-10:]:
                        if line.strip():
                            print(f"│ {line}")
                else:
                    for line in lines:
                        print(f"│ {line}")
            if proc.stderr:
                for line in proc.stderr.strip().split('\n')[-5:]:
                    print(f"│ ⚠️ {line}")

            if proc.returncode == 0:
                result["status"] = "success"
                print(f"│ ✅ 任务执行成功")
                self._log(f"任务完成 (exit code: 0)")
            else:
                result["status"] = "failed"
                print(f"│ ❌ 任务执行失败 (exit code: {proc.returncode})")
                self._log(f"任务完成 (exit code: {proc.returncode})")

        except subprocess.TimeoutExpired:
            result["error"] = "任务执行超时"
            result["status"] = "timeout"
            print(f"│ ❌ 任务超时")
            self._log(f"任务超时 (600s)")
        except Exception as e:
            result["error"] = str(e)
            print(f"│ ❌ 任务异常: {e}")
            self._log(f"任务异常: {e}")
        finally:
            # 3. 递减引用计数（始终执行）
            count = self._decrement_task_count()
            print(f"│ ℹ️  active tasks 剩余: {count}")

        print(f"└─ {'✅ 任务完成' if result['status'] == 'success' else '❌ 任务失败'} ─────────────")
        return result

    def cooldown(self):
        """
        延迟关闭模式：等待 30 秒后检查是否有 active task
        - 无 task → 关闭 clash
        - 有 task → 重置等待计时器（循环继续等）
        """
        print(f"🕒 等待 30 秒后自动关闭代理...")
        while True:
            time.sleep(30)

            # 检查 task 引用计数
            active = self._get_task_count()
            if active > 0:
                print(f"🕒 仍有 {active} 个 task 正在运行，重置 30 秒等待...")
                continue

            # 没有 task 运行，关闭 clash
            print(f"🕒 30 秒无活动，正在关闭代理...")
            stop_result = self.stop()
            self._log(f"代理已关闭")
            print(f"🕒 {stop_result['message']}")

            # 清理 cooldown.pid
            cooldown_pidfile = os.path.join(LOCK_DIR, "cooldown.pid")
            try:
                os.remove(cooldown_pidfile)
            except Exception:
                pass
            break


def main():
    """CLI 入口"""
    manager = ProxyManager()

    if len(sys.argv) < 2:
        print("用法: python3 proxy-manager.py <command>")
        print("")
        print("指令列表:")
        print("  status             查看代理状态与订阅健康状况")
        print("  url show           显示当前订阅 URL")
        print("  url set <URL>      设置/更换订阅 URL")
        print("  update             更新订阅配置（Clash 运行中时自动重启）")
        print("  start              启动代理（常驻，含后台空闲关闭）")
        print("  stop               停止代理")
        print("  test               联通测试")
        print("  speedtest          自动测速所有节点，选最快节点")
        print("  task <name> <cmd>  在代理环境执行任务（需先 start）")
        print("                     示例: task pip-install pip install torch")
        print("  cooldown           手动启动空闲关闭（30秒无 task 关代理）")
        print("  shutdown           立即关闭代理 + 停掉后台 cooldown")
        print("  help               显示此帮助")
        return

    cmd = sys.argv[1]

    if cmd == "help":
        print("可用指令: status, url <show|set>, update, start, stop, test, speedtest, task <name> <cmd>, cooldown, shutdown")
        print("说明: task 命令需要代理已运行（先执行 start）")

    elif cmd == "status":
        print(f"代理状态: {'🟢 运行中' if manager.is_running() else '🔴 已停止'}")
        print(f"订阅: {'✅ 已配置' if manager.has_subscription() else '❌ 未配置'}")
        if manager.has_subscription():
            print(f"订阅 URL: {manager.get_subscription()}")
            if manager.is_running():
                health = manager.health_check()
                print(f"联通状态: {'✅' if health.get('success') else '❌'} {health.get('message', health.get('error', 'N/A'))}")
            else:
                print(f"联通状态: ⏸️ 代理未运行，跳过检测")
        print(f"日志: {os.path.join(LOG_DIR, 'task-' + time.strftime('%Y-%m-%d') + '.log')}")

    elif cmd == "url":
        if len(sys.argv) < 3:
            print("用法: python3 proxy-manager.py url <show|set> [URL]")
            return
        sub = sys.argv[2]
        if sub == "show":
            url = manager.get_subscription()
            if url:
                print(f"当前订阅 URL: {url}")
            else:
                print("未配置订阅 URL")
        elif sub == "set":
            if len(sys.argv) < 4:
                print("请提供订阅 URL")
                return
            manager.set_subscription(sys.argv[3])
            print("✅ 订阅 URL 已更新")
            # 更新后自动拉取配置
            was_running = manager.is_running()
            result = manager.update_subscription()
            if result["success"]:
                print(f"✅ {result['message']}")
                if was_running:
                    print("🔄 Clash 正在运行，自动重启以加载新配置...")
                    manager.stop()
                    start_result = manager.start()
                    print(f"{start_result['message']}")
            else:
                print(f"❌ {result['error']}")

    elif cmd == "update":
        if not manager.has_subscription():
            print("❌ 请先配置订阅 URL: python3 proxy-manager.py url set <URL>")
            return
        was_running = manager.is_running()
        result = manager.update_subscription()
        if result["success"]:
            print(f"✅ {result['message']}")
            if "nodes" in result:
                print(f"节点列表前20: {', '.join(result['nodes'])}")
            if was_running:
                print("🔄 Clash 正在运行，自动重启以加载新配置...")
                manager.stop()
                start_result = manager.start()
                print(f"{start_result['message']}")
        else:
            print(f"❌ {result['error']}")

    elif cmd == "start":
        result = manager.start()
        print(result["message"])
        if result["success"]:
            health = manager.health_check()
            if health["success"]:
                print(f"联通测试: ✅ 延迟 {health['latency_ms']}ms")

    elif cmd == "stop":
        result = manager.stop()
        print(result["message"])

    elif cmd == "test":
        health = manager.health_check()
        if health["success"]:
            print(f"✅ 联通成功 | 延迟: {health['latency_ms']}ms | HTTP: {health.get('status_code')}")
        else:
            print(f"❌ {health.get('error', '测试失败')}")

    elif cmd == "speedtest":
        force_full = "--full" in sys.argv
        print(f"┌─ ⏱ 自动测速选优 ──────────────────────────")
        if not manager.is_running():
            print(f"│ ℹ️  代理未运行，正在启动...")
            start_result = manager.start()
            print(f"│ {start_result['message']}")
            if not start_result["success"]:
                print(f"└─ ❌ 启动失败")
                return
        result = manager.select_fastest_node(quick_mode=not force_full)
        if result["success"]:
            print(f"│ ⚡ 最优: {result['fastest']} ({result['fastest_latency']}ms)")
            print(f"│ 测试: {result['tested']}/{result['total']} 个节点可用")
            print(f"├─ 🔍 验证联通 ──────────────────────────")
            health = manager.health_check()
            print(f"│ {'✅' if health.get('success') else '❌'} {health.get('message', health.get('error', 'N/A'))}")
            print(f"└─ ✅ 测速完成")
        else:
            print(f"└─ ❌ {result.get('message', '测速失败')}")
        # 不再停止 clash（常驻服务）

    elif cmd == "task":
        if len(sys.argv) < 4:
            print("用法: python3 proxy-manager.py task <任务名> <命令>")
            print("示例: python3 proxy-manager.py task 'pip install' 'pip install torch'")
            return
        task_name = sys.argv[2]
        task_cmd = ' '.join(sys.argv[3:])
        # 去掉外层引号
        if len(task_cmd) >= 2 and task_cmd[0] == task_cmd[-1] and task_cmd[0] in ('"', "'"):
            task_cmd = task_cmd[1:-1]
        cmd_list = shlex.split(task_cmd)
        result = manager.task_wrapper(task_name, cmd_list)
        if result["status"] != "success":
            sys.exit(1)

    elif cmd == "cooldown":
        manager.cooldown()

    elif cmd == "shutdown":
        # 杀掉后台 cooldown 进程
        cooldown_pidfile = os.path.join(LOCK_DIR, "cooldown.pid")
        killed = manager._kill_process_by_pidfile(cooldown_pidfile)
        if killed:
            print("✅ 已停止 cooldown 后台进程")
        else:
            print("ℹ️  未检测到 cooldown 后台进程")
        try:
            os.remove(cooldown_pidfile)
        except Exception:
            pass
        # 关闭 clash
        result = manager.stop()
        print(result["message"])
        manager._log("代理已手动关闭 (shutdown)")

    else:
        print(f"未知指令: {cmd}")
        print("使用 'python3 proxy-manager.py help' 查看可用指令")


if __name__ == "__main__":
    main()
