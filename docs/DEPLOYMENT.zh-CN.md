# 在 Linux NAS 上部署 Mannazia

本文适用于能通过 SSH 使用 Docker Engine 和 Docker Compose 的 Linux NAS，
包括 Synology DSM（Container Manager）、QNAP（Container Station）、Unraid
以及普通 Debian/Ubuntu 主机。

Mannazia 以单容器运行，数据全部保存在三个宿主机目录中，不依赖外部数据库。

## 1. 准备条件

- Linux NAS，x86_64 或 arm64；
- 已安装 Docker Engine 20+；
- 已安装 Docker Compose v2（`docker compose` 命令）；
- 至少预留几 GB 空间，实际取决于下载的书籍；
- 能通过 SSH 登录，或能使用 NAS 的 Docker 管理界面创建 Compose 项目。

检查版本：

```sh
docker --version
docker compose version
```

## 2. 选择部署目录

目录必须位于 NAS 的本地卷，不要把 SQLite 数据库放在 SMB/NFS 网络共享上。

常见路径示例：

| 系统 | 推荐目录 |
| --- | --- |
| Synology DSM | `/volume1/docker/mannazia` |
| QNAP | `/share/Container/mannazia` |
| Unraid | `/mnt/user/appdata/mannazia` |
| Debian / Ubuntu | `/opt/mannazia` |

下面以 `/volume1/docker/mannazia` 为例。

```sh
sudo mkdir -p /volume1/docker
cd /volume1/docker
git clone <repository-url> mannazia
cd mannazia
```

如果 NAS 没有安装 Git，可以在电脑上下载仓库压缩包，再上传并解压到这个目录。

## 3. 配置文件与权限

```sh
cp .env.example .env
mkdir -p config data books
```

查看当前 NAS 用户的 UID/GID：

```sh
id -u
id -g
```

编辑 `.env`：

```dotenv
PUID=1000
PGID=1000
TZ=Asia/Shanghai
MANNAZIA_PORT=8080
```

把 `PUID` / `PGID` 改成上一步得到的数字，`TZ` 改成你的时区。

让宿主机目录对这两个 ID 可写：

```sh
sudo chown -R 1000:1000 config data books
```

把示例中的 `1000:1000` 换成实际 `PUID:PGID`。如果 NAS 用户不是 Docker
管理员，可先使用 `sudo` 创建和授权目录。

> `config/`、`data/`、`books/` 会被 bind mount 到容器。不要删除它们；它们
> 包含数据库、书目、封面、缩略图和下载的页面。

## 4. 构建并启动

在仓库目录中：

```sh
docker compose build --pull
docker compose up -d
docker compose ps
```

首次构建会下载 Node 和 Python 基础镜像，并在容器构建阶段编译前端，可能
需要几分钟。镜像完成后，容器会：

1. 自动运行 Alembic 数据库迁移；
2. 创建 `/config`、`/data`、`/books`；
3. 启动单进程 Uvicorn；
4. 通过健康检查后显示为 healthy。

检查日志和健康状态：

```sh
docker compose logs --tail=100 mannazia
curl -fsS http://127.0.0.1:8080/api/health
```

打开：

```text
http://<NAS的局域网IP>:8080/
```

API 文档：

```text
http://<NAS的局域网IP>:8080/api/docs
```

## 5. 从其他机器构建镜像（低配置 NAS）

如果 NAS 内存较小，构建前端镜像可能较慢。可以在同架构的 Linux 机器上构建，
再传到 NAS：

```sh
# 在构建机
docker build -t mannazia:0.1.0 .
docker save mannazia:0.1.0 | gzip > mannazia-0.1.0.tar.gz

# 上传到 NAS 后
gunzip -c mannazia-0.1.0.tar.gz | docker load
```

然后在 NAS 上直接启动：

```sh
docker compose up -d --no-build
```

注意宿主机架构必须一致：x86_64 NAS 用 amd64 镜像，ARM NAS 用 arm64 镜像。
如果使用 buildx 构建 ARM 镜像：

```sh
docker buildx build --platform linux/arm64 -t mannazia:0.1.0 --load .
```

## 6. 局域网访问与防火墙

- 只在内网开放 `MANNAZIA_PORT`（默认 8080）；
- 不要把 8080 直接映射到公网；
- 如需外网访问，请通过 NAS 反向代理提供 HTTPS 和认证。

如果 NAS 防火墙只允许特定网段，请把 8080 限制在局域网。

## 7. 反向代理与 HTTPS

Mannazia 没有内置登录和 TLS。推荐使用：

- Synology 反向代理；
- QNAP 反向代理；
- Nginx Proxy Manager；
- Caddy；
- 现有统一认证网关（Authentik、Authelia 等）。

Nginx 示例：

```nginx
server {
    listen 443 ssl http2;
    server_name books.example.com;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

如果反向代理与容器不在同一网络，请把 `.env` 中的
`FORWARDED_ALLOW_IPS` 设置为代理的实际地址或地址段。不要把
`FORWARDED_ALLOW_IPS=*` 用在直接暴露的服务上。

阅读器会从第三方 IIIF 服务器加载图像瓦片。浏览器直接访问这些服务器，
因此需要保证：

- 页面通过 HTTPS 打开时，IIIF 图像也应支持 HTTPS；
- 源站允许跨域访问 `info.json` 和瓦片，否则阅读器会回退到普通图片 URL。

## 8. 数据与容量规划

| 目录 | 内容 | 说明 |
| --- | --- | --- |
| `data/` | `mannazia.db`、WAL | 很小，但非常重要 |
| `books/` | 封面、缩略图、页面、CBZ | 占用空间的主体 |
| `config/` | 部署配置预留目录 | 当前通常为空 |

下载空间取决于页面数量和所选质量档位。研究档使用源站可提供的最大尺寸，
占用最大。建议：

- 为 `books/` 使用容量充足的本地卷；
- 先用少量书籍测试下载和备份流程；
- 在应用的“设置”页查看存储占用；
- 为 NAS 留出至少 10% 的剩余空间，避免 SQLite 和临时文件写入失败。

## 9. 备份与恢复

最稳妥的方式是先停止容器，再备份三个目录和 `.env`：

```sh
docker compose stop
tar -czf mannazia-backup-$(date +%F).tar.gz config data books .env
docker compose start
```

数据库和 `books/` 必须一起备份：

- 只有数据库：书目还在，但离线页面和封面文件丢失；
- 只有 `books/`：页面文件还在，但新数据库没有对应书目。

也可以使用 SQLite 在线备份命令备份数据库，但页面目录仍需要单独同步。
不要直接复制正在写入的 `mannazia.db` 作为唯一备份。

恢复：

```sh
docker compose stop
# 恢复 config/、data/、books/ 和 .env
docker compose start
docker compose logs -f mannazia
```

数据库迁移会在启动时自动执行。

## 10. 更新

```sh
cd /volume1/docker/mannazia
git pull
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 mannazia
```

更新前先备份。更新不会自动删除 `data/` 或 `books/`。应用只支持单进程，不要
启动多个容器共享同一个 SQLite 数据库。

## 11. 常见问题

### 容器启动后不断重启

```sh
docker compose logs --tail=200 mannazia
```

重点检查目录权限、磁盘空间和 `.env` 是否有非法值。

### Permission denied

确认 `.env` 中的 `PUID` / `PGID` 与目录所有者一致：

```sh
ls -ln config data books
```

然后重新授权：

```sh
sudo chown -R <PUID>:<PGID> config data books
```

### 页面打不开，但 API 正常

源站可能阻止了跨域瓦片请求，或者该书只有普通图片 URL。检查浏览器控制台，
并确认 `MANNAZIA_ALLOWED_PRIVATE_HOSTS` 是否包含局域网 IIIF 主机。

### 导入局域网 IIIF 服务器失败

默认禁止访问私网地址。只加入精确主机名，不要开放整个私网：

```dotenv
MANNAZIA_ALLOWED_PRIVATE_HOSTS=iiif.lan,library.local
```

### 端口冲突

修改 `.env`：

```dotenv
MANNAZIA_PORT=8090
```

然后：

```sh
docker compose up -d
```

### 构建镜像时内存不足

在另一台同架构 Linux 机器上构建并用 `docker save` / `docker load` 传输，
见第 5 节。

## 12. 安全底线

- 不要把 8080 直接暴露到公网；
- 使用 HTTPS 反向代理；
- 加上访问认证，或只在可信内网使用；
- 不要把 `.env`、数据库或 `books/` 提交到 Git；
- 定期备份；
- 只用官方仓库或自己构建的镜像；
- 一次只运行一个容器实例。
