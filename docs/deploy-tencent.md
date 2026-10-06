# 腾讯云轻量应用服务器部署（Ensemble 单人版）

> 目标：把"本机 docker-compose 可玩"升级为"公网 IP 可玩"。全流程约 30 分钟。

## 1. 购买与初始化

- 腾讯云「轻量应用服务器」：Ubuntu 22.04，2 核 2G 起（单人玩足够）；
- 防火墙放行 `80/tcp`（HTTPS 再加 443），22 默认放行；
- 纯 IP 访问无需域名与备案；绑域名走 HTTPS 需备案。

## 2. 安装 Docker

SSH 登录后：

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker   # 免 sudo（重登生效）
docker compose version
```

## 3. 上传代码

```bash
git clone <你的仓库地址> ensemble && cd ensemble   # 或 scp 上传整个目录
```

## 4. 配置与启动

```bash
cp .env.example .env
vim .env          # 填 DASHSCOPE_API_KEY / DEEPSEEK_API_KEY
mkdir -p data
docker compose up -d --build
docker compose ps           # frontend running / backend healthy
```

## 5. 验收（M4 出口标准：公网单人可玩）

- 浏览器打开 `http://<公网IP>/` → 新建战役 → 进入房间；
- 提交行动 → **立刻结算**（无等待窗口）；结算完自动可输入下一回合；
- 刷新页面 → 历史完整回放，可继续行动；
- 换一台设备 / 另一个浏览器打开同地址 → 大厅「进行中」**看不到**前一浏览器的战役（归属隔离生效）；
- 玩到结局 → 结局叙事完整展示；
- GM 暗骰不出现在骰子日志中；
- 命令行冒烟：`curl http://<公网IP>/api/modules` 返回模组列表 JSON。

## 6. 日常运维

```bash
docker compose logs -f backend     # 看日志
docker compose up -d --build       # 更新代码后重建
docker compose down                # 停止
```

- 数据都在 `./data/ensemble.db`（SQLite），定期 `scp` 备份即可；
- 重启服务器后若未自启，见下方 systemd。

### 开机自启（可选）

`/etc/systemd/system/ensemble.service`：

```ini
[Unit]
Description=Ensemble docker compose
After=docker.service
Requires=docker.service

[Service]
WorkingDirectory=/home/ubuntu/ensemble
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now ensemble.service`

## 7. HTTPS（可选，绑定域名时）

- 腾讯云 SSL 证书（免费）挂载进 frontend 容器，nginx 加 443 server；
- 或前置 Caddy 反代；WebSocket 需 Upgrade 头透传（本项目 nginx.conf 已配置）。
