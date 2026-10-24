# Mannazia 离线部署包

这个压缩包包含：

```text
mannazia-offline-0.1.0/
    compose.yaml
    .env.example
    install.sh
    images/
        mannazia-amd64.tar
        mannazia-arm64.tar
    README.md
    DEPLOYMENT.zh-CN.md
    LICENSE
```

不需要联网，也不需要 Node.js、Python 或 npm。NAS 只需要已经安装
**Docker Engine + Docker Compose**（优先 v2；脚本也兼容 v1 的 `docker-compose`）。

## 1. 上传并解压

把 `mannazia-offline-0.1.0.tar.gz` 上传到 NAS，例如：

```sh
mkdir -p /volume1/docker
cd /volume1/docker
tar -xzf mannazia-offline-0.1.0.tar.gz
cd mannazia-offline-0.1.0
```

QNAP 可使用 `/share/Container/`，Unraid 可使用 `/mnt/user/appdata/`。

## 2. 检查配置（可选）

安装脚本第一次运行时会自动：

- 识别机器架构；
- 加载对应的 Docker 镜像；
- 创建 `config/`、`data/`、`books/`；
- 从 `.env.example` 创建 `.env`，并填入当前用户的 UID/GID。

如果想提前修改端口、时区或 PUID/PGID：

```sh
cp .env.example .env
nano .env
```

至少检查：

```dotenv
PUID=1000
PGID=1000
TZ=Asia/Shanghai
MANNAZIA_PORT=8080
```

## 3. 安装并启动

如果当前用户有 Docker 权限：

```sh
sh install.sh
```

如果 Docker 需要 root，或 NAS 用户不在 docker 组：

```sh
sudo sh install.sh
```

脚本会加载镜像并启动容器，不需要访问互联网，也不会执行 `docker build`。

## 4. 访问

```text
http://<NAS-IP>:8080/
```

健康检查：

```sh
docker compose -p mannazia -f compose.yaml ps
docker compose -p mannazia -f compose.yaml logs --tail=100 mannazia
curl http://127.0.0.1:8080/api/health
```

## 5. 修改端口

编辑 `.env`：

```dotenv
MANNAZIA_PORT=8090
```

然后：

```sh
docker compose -p mannazia -f compose.yaml up -d
```

容器内部始终使用 8080，不需要改 compose 的右侧端口。

## 6. 备份与更新

备份时停止容器，并同时保存 `data/`、`books/`、`config/` 和 `.env`：

```sh
docker compose -p mannazia -f compose.yaml stop
tar -czf mannazia-backup-$(date +%F).tar.gz config data books .env
docker compose -p mannazia -f compose.yaml start
```

以后更新时，用新的离线包替换 `mannazia:0.1.0` 镜像并重新启动容器。

## 7. 安全提醒

- 不要直接把 8080 暴露到公网；
- 外网访问请使用 HTTPS 反向代理和认证；
- 不要把数据库或 `books/` 放在 SMB/NFS 网络共享上；
- 只运行一个容器实例共享同一个 SQLite 数据库。

更完整的 NAS 部署说明见同目录下的
[`DEPLOYMENT.zh-CN.md`](DEPLOYMENT.zh-CN.md)。
