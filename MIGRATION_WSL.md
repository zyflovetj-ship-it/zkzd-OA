# zk-oa 迁移到 WSL + Ubuntu 部署说明

> 本文件随部署包一起分发，用于在 WSL2 + Ubuntu 上完成部署。

---

## 一、这个包里有什么 / 没有什么

**包含**：全部源码、Docker 编排与 Dockerfile、Nginx 配置、Alembic 迁移脚本（0001–0011）、
测试套件、前端品牌资产（logo / favicon / PWA 图标）、全部文档。

**已排除**（属于可再生或平台相关产物，部署时自动重建）：

| 排除项 | 原因 |
|---|---|
| `backend/.venv` | 176MB，宿主平台专用二进制，Ubuntu 上无用 |
| `frontend/node_modules` | 293MB，需按目标平台重新安装 |
| `frontend/dist` | 前端构建产物，镜像构建时重新生成 |
| `backend/*.db` | 开发用 SQLite 库，生产用 PostgreSQL |
| `backend/uploads/` | **冒烟测试产生的 9–15 字节测试文件**，非真实附件 |
| `__pycache__` / `*.pyc` / `.pytest_cache` / `*.log` | 缓存与日志 |

> ⚠️ 如果原环境里有**真实附件**需要保留，请单独拷贝 `backend/uploads/` 目录，
> 并在部署后放进 `oa_uploads` 卷（见第五节）。

包内所有文件均为 **LF 行尾**，`backend/run.sh` 保留可执行位，已实测验证。

---

## 二、传输与解包

在 **Windows** 侧把 tar 包拷进 WSL（或直接用 `scp` 传到服务器）：

`@bash
# 方式一：已经在 WSL 里，从 Windows 挂载点拷贝
cp /mnt/c/Users/<你的用户名>/Downloads/zk-oa-ubuntu-deploy.tar.gz ~/

# 方式二：从 Windows 传到远程服务器
# scp zk-oa-ubuntu-deploy.tar.gz user@server:~/

# 校验完整性（对比打包时给出的 SHA256）
sha256sum zk-oa-ubuntu-deploy.tar.gz

# 解包
mkdir -p ~/zk-oa && tar -xzf zk-oa-ubuntu-deploy.tar.gz -C ~/zk-oa --strip-components=1
cd ~/zk-oa && ls
`@

> **务必解包到 WSL 原生文件系统（如 `~/zk-oa`），不要放在 `/mnt/c/...`。**
> `/mnt/c` 走 drvfs，`npm ci` 处理三万个文件会慢一个数量级，Docker 构建同样极慢。

---

## 三、WSL 环境准备

`@bash
# 1) 确认是 WSL2（在 PowerShell 执行，VERSION 必须是 2）
#    wsl.exe -l -v

# 2) 启用 systemd（否则 Docker 每次都要手动起）
sudo tee /etc/wsl.conf > /dev/null <<'EOF'
[boot]
systemd=true
EOF
# 然后在 PowerShell 执行 wsl --shutdown，再重新进入 WSL

# 3) 安装 Docker Engine（与裸机 Ubuntu 命令相同）
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/keyrings/docker.gpg
sudo chmod a+r /etc/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 4) 免 sudo 使用 docker
sudo usermod -aG docker $USER
# 之后关闭并重开 WSL 终端使组权限生效

# 5) 确认 compose 是 v2
docker compose version     # 应输出 v2.x，命令必须是 docker compose（带空格）
`@

**不需要安装**：Python、Node、PostgreSQL、Nginx、gcc。
依赖全部在容器内解决，且已验证 15 个 Python 依赖在 linux x86_64 / aarch64 上都有预编译 wheel，无需编译工具链。

---

## 四、配置与启动

`@bash
cd ~/zk-oa
cp .env.example .env
`@

编辑 `.env`，三个**必填**项（缺失时 `docker compose` 会直接报错，不会静默产出坏部署）：

| 变量 | 说明 |
|---|---|
| `JWT_SECRET` | `python3 -c 'import secrets;print(secrets.token_hex(32))'` |
| `VITE_API_BASE` | **浏览器可达**的后端地址。仅本机用 `http://localhost:8000`；局域网用 `http://<Windows主机IP>:8000` |
| `CORS_ORIGINS` | 对应前端地址，如 `http://localhost:5173` 或 `http://<Windows主机IP>:5173` |

`@bash
docker compose up -d --build

# 验证
docker compose ps
curl http://localhost:8000/health     # {"status":"ok"}
curl http://localhost:8000/ready      # {"status":"ready"}
curl -s http://localhost:5173/ | head -5
`@

浏览器打开 `http://localhost:5173`，用 `admin / admin123` 登录，
**登录后立刻在「人事管理 → 员工管理」修改默认密码**。

> 注意：系统只预置 `admin` 一个账号；`manager` / `employee` 角色会预置，
> 但**不会**创建同名账号，需自行在「员工管理」中新建。

---

## 五、局域网访问（WSL 特有，最容易踩的坑）

WSL2 默认是 NAT 网络，**局域网其他机器默认访问不到 WSL 里的端口**。二选一：

### 方案 A：端口转发（所有 Win10/11 可用，但 WSL 每次重启后要重做）

在 **PowerShell（管理员）** 执行：

`@powershell
$wslIp = (wsl hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenport=5173 listenaddress=0.0.0.0 connectport=5173 connectaddress=$wslIp
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=$wslIp
New-NetFirewallRule -DisplayName "zk-oa" -Direction Inbound -LocalPort 5173,8000 -Protocol TCP -Action Allow
`@

### 方案 B：镜像网络模式（Win11 22H2+，推荐）

在 `C:\Users\<你的用户名>\.wslconfig` 写入：

`@ini
[wsl2]
networkingMode=mirrored
`@

然后 `wsl --shutdown` 重启。此后 WSL 共用 Windows 主机 IP，局域网用 Windows 的 IP 即可访问。

> **铁律**：`VITE_API_BASE` 永远不要填 WSL 的 `172.x.x.x` 地址——它每次重启都变，且局域网机器路由不到。
> 改 `VITE_API_BASE` 后必须重建前端镜像：`docker compose up -d --build frontend`

---

## 六、迁移旧数据（可选）

若原环境有真实附件（不是测试文件）：

`@bash
# 附件拷进 oa_uploads 卷
docker compose cp /path/to/old/uploads/. backend:/app/uploads/
docker compose restart backend
`@

SQLite 开发库（`oa.db` / `final.db`）**不要**直接用于生产，系统没有内置的 SQLite→PostgreSQL 搬迁工具。
生产环境首次启动会自动执行 `alembic upgrade head` 并灌入种子数据。

---

## 七、排错速查

| 现象 | 原因与处理 |
|---|---|
| `docker compose up` 报缺少 JWT_SECRET / VITE_API_BASE | `.env` 未填必填项，按报错提示补齐 |
| 前端页面打开但请求全失败 | `VITE_API_BASE` 填成了 localhost 却从远程访问；改成浏览器可达地址并 `--build frontend` |
| 浏览器控制台报 CORS | `CORS_ORIGINS` 与实际访问地址不一致 |
| 局域网访问不通 | 见第五节，需端口转发或镜像网络模式 |
| 附件上传后重启容器丢失 | 确认 `oa_uploads` 卷已挂载（`docker volume ls`） |
| `docker: command not found` | Docker 未安装，或未重开终端使 docker 组生效 |
| `permission denied ... docker.sock` | 未加入 docker 组或未重开终端 |
| shell 脚本报 `\r: command not found` | 文件行尾符被转成了 CRLF，用 `sed -i 's/\r$//' 文件` 修正 |

---

## 八、重要提醒：WSL 不适合对外生产

WSL2 是开发环境，不是服务器：不会随 Windows 开机自启、`wsl --shutdown` 会杀掉所有容器、
IP 不稳定、Windows 更新重启会中断服务。

**适合**：内网演示、功能验收、小范围试用。
**生产建议**：换真正的 Ubuntu Server。届时把 `~/zk-oa` 整个目录打包拷过去即可，
代码侧无需任何改动（已确认无硬编码绝对路径）。
