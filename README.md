# smart-analytics

极简、以隐私为先的网站分析。自托管，无 Cookie，无追踪标识。**支持多站点 / 多租户**：单个账户可管理多个站点，每个站点拥有独立的追踪脚本与数据隔离。

## 快速开始

```bash
# 安装
uv tool install smart-analytics

# 首次启动后访问 /register 注册首个管理员账户（注册者自动成为默认站点 owner）。
# 如需固定密码（推荐生产环境），设环境变量后启动会据此自动创建管理员：
export SMART_ANALYTICS_PASSWORD="your-secret-password"
export SMART_ANALYTICS_SECRET_KEY="$(openssl rand -hex 32)"

# 运行
smart-analytics
```

登录后进入「站点管理」创建一个站点，会得到一个**专属追踪脚本**（每个站点独立 token）：

```html
<script src="https://your-analytics-domain/s/<token>.js" defer></script>
```

把这段代码加入对应网站即可；不同站点使用各自的 token，数据完全隔离。在 `http://localhost:8000/` 查看仪表盘，通过顶部站点切换器在多个站点间切换。

### 一行命令（无需安装）

```bash
uvx smart-analytics
```

### 从源码安装

```bash
git clone https://github.com/fireboltby/smart-analytics.git
cd smart-analytics
uv sync
uv run smart-analytics
```

<details>
<summary>使用 pip 而非 uv</summary>

```bash
pip install smart-analytics
smart-analytics
```

或从源码安装：
```bash
git clone https://github.com/fireboltby/smart-analytics.git
cd smart-analytics
python -m venv .venv && source .venv/bin/activate
pip install -e .
smart-analytics
```
</details>

---

## 功能特性

- **隐私优先**：无 Cookie、无指纹采集、不存储任何个人数据
- **多站点 / 多租户**：单账户管理多个站点，每站独立追踪脚本与数据隔离（按 `site_id`）；支持多用户与站点成员
- **账户体系**：邮箱 + 密码注册 / 登录 / 登出，Web 界面管理站点与成员
- **轻量自托管**：基于 FastAPI + SQLite（单库多租户），单进程运行，无需外部服务或数据库
- **离线 GeoIP 定位**：基于访客 IP 的**国家 / 省份 / 城市**级定位（DB-IP 库，无需第三方 API 或密钥）
- **高频 IP 模块**：识别高频访问 IP 并展示其地理位置（国家 - 城市）
- **机器人过滤**：自动识别并分离机器人流量
- **页面停留时长**：记录真实互动时长，而非仅统计页面加载
- **地理与设备分布**：查看访客来源国家 / 地区 / 城市及所用设备类型
- **暗色模式 UI**：护眼界面
- **热门页面与流量来源**：Top 页面排行，来源域名与搜索关键词分析
- **访问时段分布**：按 24 小时 / 星期维度观察流量规律
- **环比对比**：独立访客、浏览量、停留时长的同期变化
- **实时在线**：近 5 分钟实时在线人数，仪表盘自动轮询
- **新 / 老访客**：基于匿名访客标识区分新访客与回访访客
- **UTM 渠道追踪**：按来源（utm_source）/ 媒介（utm_medium）/ 活动（utm_campaign）维度统计
- **会话分析（估算）**：跳出率、平均会话时长、入口页 / 出口页（基于会话重建，属估算值）
- **浏览器 / 操作系统分布（粗分）**：纯 User-Agent 粗粒度统计，不采集屏幕分辨率等指纹信息
- **灵活的时间范围与统计间隔**：仪表盘支持 1 小时 / 2 小时 / 24 小时 / 7 天 / 30 天时间范围，以及 1 分钟 / 5 分钟 / 15 分钟 / 1 小时统计间隔

## 工作原理

1. **每个站点有独立 token**，其追踪脚本为 `/s/<token>.js`
2. **访客打开你的页面** → `/s/<token>.js` 向 `/t` 发送一次 POST 请求（携带站点 token）
3. **服务端对 `站点ID:IP:UA` 做哈希** → 生成匿名访客标识（原始 IP 绝不存储，且不同站点不会串）
4. **页面离开时** → 信标将页面停留时长发送至 `/d`
5. **仪表盘** → 按当前站点聚合并可视化这些数据

无 Cookie。无 localStorage。跨站无追踪。

## 配置

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `SMART_ANALYTICS_PASSWORD` | 无（留空则走 /register 注册流程） | 设此环境变量后，首次启动会据此自动创建管理员账户；不设则访问 /register 手动注册 |
| `SMART_ANALYTICS_SECRET_KEY` | `change-this...` | 会话签名密钥（请生成随机字符串） |
| `SMART_ANALYTICS_ALLOWED_ORIGINS` | `[]` | 全局 CORS：限制可上报的域名（空 = 允许所有）。每站还可在站点管理中单独设置 `allowed_origins` 防跨站刷量 |
| `SMART_ANALYTICS_DB_PATH` | `data/smart_analytics.db` | SQLite 数据库位置（相对项目根目录） |
| `SMART_ANALYTICS_HOST` | `0.0.0.0` | 绑定的主机 |
| `SMART_ANALYTICS_PORT` | `8000` | 监听端口 |

## 部署

### 使用仓库内置部署脚本（推荐）

仓库 `deploy/linux/` 提供了一键部署所需文件：

- `setup.sh` — 安装依赖、创建 systemd 服务、配置 nginx 的一键脚本
- `smart-analytics.service` — systemd unit 文件
- `nginx-smart-analytics.conf` — nginx 反向代理配置
- `DEPLOY.md` — 详细部署步骤

```bash
# 以 www-data 为例
sudo bash deploy/linux/setup.sh
```

### Systemd（手动）

```ini
[Unit]
Description=smart-analytics
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/smart-analytics
Environment="SMART_ANALYTICS_PASSWORD=your-password"
Environment="SMART_ANALYTICS_SECRET_KEY=your-secret-key"
ExecStart=/usr/local/bin/smart-analytics
Restart=always

[Install]
WantedBy=multi-user.target
```

### 反向代理（nginx）

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### Cloudflare

smart-analytics 在 Cloudflare 后会自动读取 `cf-connecting-ip`（真实访客 IP）与 `cf-ipcountry`（国家）请求头；地理定位同时由内置**离线 GeoIP 库（DB-IP）**完成，同样覆盖非 Cloudflare 场景。

> 离线 GeoIP 需要 MaxMind / DB-IP 的 `.mmdb` 数据库文件，默认不随仓库分发。下载方式：
> ```bash
> python scripts/fetch_geoip.py
> ```
> 未下载时，地理定位将降级（仅缺失省 / 市级），不影响采集与其他功能。

## 命令行选项

```
smart-analytics [OPTIONS]

Options:
  --host TEXT    绑定的主机 [默认: 0.0.0.0]
  --port INTEGER 监听端口 [默认: 8000]
  --help         显示此帮助信息并退出
```

## API

| 接口 | 方法 | 说明 |
|----------|--------|-------------|
| `/t` | POST | 记录一次页面浏览（携带站点 token） |
| `/d` | POST | 更新页面停留时长 |
| `/s/<token>.js` | GET | 某站点的追踪脚本（替代全局 snippet.js） |
| `/api/realtime` | GET | 近 5 分钟实时在线人数（需登录，按当前站点） |
| `/` | GET | 仪表盘（需登录） |
| `/logs` | GET | 原始日志视图（需登录） |
| `/login` | GET/POST | 登录（邮箱 + 密码） |
| `/register` | GET/POST | 注册账户（首个注册者成为默认站点 owner） |
| `/logout` | GET | 登出 |
| `/sites` | GET | 站点管理页 |
| `/sites/create` | POST | 创建站点（生成独立 token） |
| `/sites/delete` | POST | 删除站点（级联清理该站数据） |
| `/switch-site` | GET | 切换当前站点 |
| `/settings` | GET | 设置页（修改密码等） |
| `/api/change-password` | POST | 修改密码 |
| `/api/create-user` | POST | 创建站点成员账户 |

## 开发 / 测试

```bash
# uv 环境
uv sync
uv run pytest

# 或 pip 环境（依赖已安装）
pytest
```

仓库 `tests/` 包含单元测试与端到端流程测试，覆盖认证边界、追踪采集、站点隔离、仪表盘聚合等。

## 许可证

MIT
