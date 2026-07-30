# smart-analytics

极简、以隐私为先的网站分析。自托管，无 Cookie，无追踪标识。

![Dashboard](docs/dashboard.png)

## 快速开始

```bash
# 安装
uv tool install smart-analytics

# 配置（创建一个 .env 文件，或直接设置环境变量）
export TINY_ANALYTICS_PASSWORD="your-secret-password"
export TINY_ANALYTICS_SECRET_KEY="$(openssl rand -hex 32)"

# 运行
smart-analytics
```

将以下代码加入你的网站：
```html
<script src="https://your-analytics-domain/snippet.js" defer></script>
```

就是这样。在 `http://localhost:8000/` 查看你的仪表盘。

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
- **轻量自托管**：基于 FastAPI + SQLite，单进程运行，无需外部服务或数据库
- **机器人过滤**：自动识别并分离机器人流量
- **页面停留时长**：记录真实互动时长，而非仅统计页面加载
- **地理与设备分布**：查看访客来源国家/地区及所用设备类型
- **暗色模式 UI**：护眼界面
- **热门页面与流量来源**：Top 页面排行，来源域名与搜索关键词分析
- **访问时段分布**：按 24 小时 / 星期维度观察流量规律
- **环比对比**：独立访客、浏览量、停留时长的同期变化
- **实时在线**：近 5 分钟实时在线人数，仪表盘自动轮询
- **新 / 老访客**：基于匿名访客标识区分新访客与回访访客
- **UTM 渠道追踪**：按来源（utm_source）/ 媒介（utm_medium）/ 活动（utm_campaign）维度统计
- **会话分析（估算）**：跳出率、平均会话时长、入口页 / 出口页（基于会话重建，属估算值）
- **浏览器 / 操作系统分布（粗分）**：纯 User-Agent 粗粒度统计，不采集屏幕分辨率等指纹信息

## 截图

<details>
<summary>登录</summary>

![Login](docs/login.png)
</details>

<details>
<summary>日志视图</summary>

![Logs](docs/logs.jpg)
</details>

## 工作原理

1. **访客打开你的页面** → `snippet.js` 向 `/t` 发送一次 POST 请求
2. **服务端对 IP+UA 做哈希** → 生成匿名访客标识（原始 IP 绝不存储）
3. **页面离开时** → 信标将页面停留时长发送至 `/d`
4. **仪表盘** → 聚合并可视化这些数据

无 Cookie。无 localStorage。跨站无追踪。

## 配置

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `TINY_ANALYTICS_PASSWORD` | `changeme` | 仪表盘登录密码 |
| `TINY_ANALYTICS_SECRET_KEY` | `change-this...` | 会话签名密钥（请生成随机字符串） |
| `TINY_ANALYTICS_ALLOWED_ORIGINS` | `[]` | 限制可上报的域名（空 = 允许所有） |
| `TINY_ANALYTICS_DB_PATH` | `./tiny_analytics.db` | SQLite 数据库位置 |
| `TINY_ANALYTICS_HOST` | `0.0.0.0` | 绑定的主机 |
| `TINY_ANALYTICS_PORT` | `8000` | 监听端口 |

## 部署

### Systemd

```ini
[Unit]
Description=smart-analytics
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/smart-analytics
Environment="TINY_ANALYTICS_PASSWORD=your-password"
Environment="TINY_ANALYTICS_SECRET_KEY=your-secret-key"
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

smart-analytics 会自动读取 `cf-connecting-ip` 与 `cf-ipcountry` 请求头，在 Cloudflare 后获取准确的地理与 IP 数据。

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
| `/t` | POST | 记录一次页面浏览 |
| `/d` | POST | 更新页面停留时长 |
| `/snippet.js` | GET | 追踪脚本 |
| `/api/realtime` | GET | 近 5 分钟实时在线人数（需登录） |
| `/` | GET | 仪表盘（需登录） |
| `/logs` | GET | 原始日志视图（需登录） |

## 许可证

MIT
