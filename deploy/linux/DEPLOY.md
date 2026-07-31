# smart-analytics 生产部署手册（Linux）

> **零侵入原则**：本项目与 HabitHero 完全独立部署——独立系统用户、独立虚拟环境、
> 独立数据库文件、独立 systemd 单元、独立 nginx 反代块、独立端口（8001）。
> 本手册与脚本**不会读取 / 修改 / 停止 HabitHero 的任何文件或进程**。

---

## 1. 资源分配对照（避免和 HabitHero 冲突）

| 项目          | smart-analytics            | HabitHero（已存在，勿动） |
|---------------|----------------------------|---------------------------|
| 系统用户      | `smartanalytics`           | HabitHero 自有用户        |
| 代码/venv     | `/opt/smart-analytics/`    | HabitHero 目录            |
| 数据库        | `…/data/smart_analytics.db`| HabitHero 自有 db         |
| 监听端口      | `8001`（回环）             | `9999`                    |
| systemd 单元  | `smart-analytics.service`  | HabitHero 单元            |
| nginx         | 新增 `conf.d/smart-analytics.conf`（独立 server 块） | HabitHero 现有配置不动 |

---

## 2. 前置条件

- 一台已运行 HabitHero 的 Linux 服务器（本部署不影响它）。
- 具备 `sudo` / root 权限。
- 已安装：Python 3.10+、`nginx`、`systemd`、`git`（用于取代码）。
- （可选）域名一个，用于 analytics 子域名 + HTTPS。

---

## 3. 一键部署

```bash
# 1) 把仓库放到 /opt/smart-analytics（或任意路径，作为脚本第一个参数传入）
sudo git clone <你的仓库地址> /opt/smart-analytics
cd /opt/smart-analytics

# 2) 运行部署脚本（自动：建用户→建 venv→装依赖→生成 .env→注册 systemd→写 nginx 配置）
sudo bash deploy/linux/setup.sh
```

脚本会：
1. 创建无登录权限的系统用户 `smartanalytics`，专用于运行本服务。
2. 在 `/opt/smart-analytics/venv` 建隔离虚拟环境并 `pip install -e .`（依赖仅
   fastapi / uvicorn / pydantic* / python-multipart / itsdangerous / jinja2，无需数据库驱动）。
3. **首次自动生成 `.env`**，内含：
   - `SMART_ANALYTICS_SECRET_KEY`：固定 64 位十六进制随机串（**关键**，避免重启会话失效）；
   - `SMART_ANALYTICS_PASSWORD`：首个管理员初始密码（脚本会打印，**请保存**）；
   - 端口 `8001`、独立 DB 路径、关闭公开注册。
4. 注册并启动 `smart-analytics.service`（崩溃自动重启）。
5. 写入独立 nginx 反代配置 `/etc/nginx/conf.d/smart-analytics.conf`。

> 若 `.env` 已存在，脚本会跳过生成，保留原有密钥与密码（幂等、可重复运行）。

---

## 4. 配置 nginx 反代

编辑刚写入的 `/etc/nginx/conf.d/smart-analytics.conf`，把
`server_name analytics.example.com;` 改成你的真实子域名，然后：

```bash
sudo nginx -t && sudo systemctl reload nginx
```

建议用 certbot 申请 HTTPS（证书就绪后自动补 443 + 重定向，无需手改）：

```bash
sudo certbot --nginx -d analytics.example.com
```

> 不想加子域名也可用同域名 `/analytics/` 路径方案，见 conf 文件内「方案 B」注释，
> 但需额外给应用设 `--root-path` 并调整前端追踪脚本 base，生产一般更推荐子域名。

---

## 5. 验证与运维

```bash
# 服务状态
systemctl status smart-analytics.service

# 实时日志
journalctl -u smart-analytics.service -f

# 端口监听（应为 127.0.0.1:8001）
ss -ltnp | grep 8001

# 通过域名访问： https://analytics.example.com/
# 首次用 setup.sh 打印的管理员初始密码登录（邮箱 admin@localhost）。
```

---

## 6. 升级

```bash
cd /opt/smart-analytics
sudo git pull
sudo bash deploy/linux/setup.sh        # 复用现有 .env，仅刷新依赖/单元/配置
sudo systemctl restart smart-analytics.service
```

---

## 7. 备份

只需备份数据库文件（轻量、自包含）：

```bash
# 建议加入 cron，例如每日一次
cp /opt/smart-analytics/data/smart_analytics.db /backup/sa-$(date +%F).db
```

---

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 重启后所有用户被登出 | `SECRET_KEY` 未固定（每次随机） | 确认 `.env` 中有固定 `SMART_ANALYTICS_SECRET_KEY`，重启服务 |
| `/register` 仍可公开访问 | `SMART_ANALYTICS_OPEN_REGISTER` 未设 false | 在 `.env` 显式设为 `false` 并重启 |
| nginx 502 | 应用未起 / 端口不对 | `systemctl status smart-analytics.service` 与 `ss -ltnp \| grep 8001` |
| 静态资源 404 | 反向代理未透传 | 确认 `proxy_pass http://127.0.0.1:8001;`（无多余路径截断） |

---

## 9. 与 HabitHero 的关系（再次声明）

- 二者共享同一台 Linux 主机，但**进程、端口、数据库、配置、运行用户全部独立**。
- 本部署新增的文件均位于 `/opt/smart-analytics/` 与 `/etc/nginx/conf.d/smart-analytics.conf`，
  不涉及 HabitHero 任何目录或 `systemctl` 单元。
- 如未来需要停止 smart-analytics，仅 `sudo systemctl stop smart-analytics.service`，
  HabitHero 不受影响、继续运行。

---

## 10. 启用国家/地区识别（离线 GeoIP）

仪表盘「国家/地区」默认只认 Cloudflare 的 `CF-IPCountry` 头。若前端**未套 Cloudflare**，
该头不存在，国家恒为空。改为用已采集的访客 IP 查本地 GeoIP 库（DB-IP 免费版，CC-BY 4.0，无需 license key）。

```bash
cd /www/wwwroot/smart-analytics        # 或你的部署目录
# 1) 安装新依赖（geoip2）
./venv/bin/pip install -e .
# 2) 下载 GeoIP 库到 data/GeoIP.mmdb（约 8MB，自动选最近月份）
python scripts/fetch_geoip.py
# 3) 回填历史记录（country 为 NULL 且有 IP 的行）
SMART_ANALYTICS_DB_PATH=/www/wwwroot/smart-analytics/data/smart_analytics.db \
    python scripts/backfill_country.py
# 4) 重启服务生效
sudo systemctl restart smart-analytics.service
```

- 库文件 `data/GeoIP.mmdb` **不入库**（已加 `.gitignore`），需每台服务器自行下载。
- 下载失败多为服务器无外网：确认能访问 `https://download.db-ip.com`。
- 展示国家数据须保留页脚 DB-IP 署名（CC-BY 4.0 要求），勿删除。
- 想换库位置：设环境变量 `SMART_ANALYTICS_GEOIP_DB=/path/GeoIP.mmdb`。
- 定期更新：把第 2 步加入 cron（每月一次）即可保持库新鲜。

