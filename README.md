<p align="center">
  <img src="frontend/public/mannaz-logo.svg" width="76" alt="Mannazia logo">
</p>

<h1 align="center">Mannazia</h1>

<p align="center">
  自托管的 IIIF 数字图书馆，为个人书架和 NAS 而设计。
</p>

<p align="center">
  <a href="README.en.md">English</a> · <strong>中文</strong>
</p>

---

Mannazia 可以导入 IIIF Presentation API 2.1 / 3.0 Manifest，预览并编目书籍，
从原始 IIIF 图像服务在线阅读，或按需把页面保存到自己的 NAS。

> **核心理念：书目记录与本地页面相互独立。**
>
> 导入一本书不会下载整本书，只会缓存一张清晰封面并保存书目信息。删除本地页面时，
> 书目记录、封面和缩略图仍会保留。

整个应用以一个 Docker 容器运行，使用 SQLite，不依赖 PostgreSQL、Redis、
Elasticsearch、消息队列或 GPU。

## 功能

- 支持 IIIF Presentation API **2.1** 和 **3.0**，统一为内部模型。
- 导入前预览标题、作者、封面、权利信息、Canvas 数量、图像服务和解析警告。
- 自动选择封面页，并把封面单独缓存为清晰的书架图片。
- 重复 Manifest 检测、可编辑元数据和标签。
- 远程阅读使用 OpenSeadragon 与 IIIF Image API 瓦片；普通图片 URL 有回退显示。
- 阅读进度按稳定的源 Canvas 标识保存。
- 导入后在后台缓存每页缩略图，阅读器缩略图栏优先使用本地文件。
- 可暂停、恢复、取消和重试的 NAS 下载，支持并发限制、超时和逐页状态。
- 四档下载质量：阅读、标准、欣赏、研究。
- 完整下载会打包为 `book.cbz`，减少散文件并可直接作为 CBZ 使用。
- 页面写入使用临时文件、图像校验、SHA-256 和原子替换；离线状态需要完整验证。
- 删除本地页面时保留高质量封面缓存。
- 书架搜索覆盖标题、作者、描述、语言、日期、权利、标签和全部元数据。
- 英文 / 中文界面，语言选择会持久化。
- 响应式界面和键盘操作。
- 面向 SSRF 的抓取层：阻止私网、回环和链路本地地址，校验并固定 DNS，重定向逐跳复核。
- SQLite WAL、外键、Alembic 迁移和重启后的状态对账。

## 快速开始

需要 Docker Engine 20+ 和 Docker Compose 插件。

```sh
git clone <repository-url> mannazia
cd mannazia
cp .env.example .env
mkdir -p config data books
```

编辑 `.env`，把 `PUID` / `PGID` 设置为 NAS 上应拥有这些目录的用户。然后：

```sh
docker compose build
docker compose up -d
docker compose ps
```

打开：

- 界面：`http://<NAS-IP>:8080/`
- API 文档：`http://<NAS-IP>:8080/api/docs`
- 健康检查：`http://<NAS-IP>:8080/api/health`

`MANNAZIA_PORT` 只修改宿主机端口；容器内部始终监听 8080。

### 持久化目录

| 宿主机目录 | 容器目录 | 内容 |
| --- | --- | --- |
| `./config` | `/config` | 部署配置预留目录 |
| `./data` | `/data` | SQLite 数据库及其 WAL 文件 |
| `./books` | `/books` | Manifest 快照、封面、缩略图、页面与 CBZ |

`data/`、`books/` 和 `config/` 默认不会提交到 Git。

## 首次使用

1. 打开“导入”，粘贴 IIIF Manifest URL。
2. 预览元数据、权利信息、页数和警告；此时不会下载书页。
3. 确认后加入书架，Mannazia 会缓存封面并把书标记为“在线”。
4. 打开书籍即可远程阅读。支持 IIIF Image API 的页面按视口加载瓦片。
5. 在书籍页点击“下载到 NAS”，选择阅读、标准、欣赏或研究档位。
6. 下载完成后，所有页面都会校验并打包为 `book.cbz`，书籍变为“已离线”。
7. “删除本地页面”只删除页面和 CBZ，保留书目、封面和缩略图。

## 下载质量

下载菜单提供四个档位：

- **阅读**：优先节省空间，文字清晰、插图可辨。
- **标准**：兼顾文字、图表和普通插图，适合多数书籍。
- **欣赏**：更高细节，适合插图和图版。
- **研究**：请求源站可提供的最大尺寸，本地不缩放、不重新压缩。

前三档在本地处理（必要时调整尺寸并重新压缩），始终保持彩色。研究档保留下载
得到的字节，但“最大可用尺寸”不一定等于原始档案文件；界面中会明确提示。

完整下载会生成 `book.cbz`。部分下载保留散页，以便继续重试；只有全部必需页面
校验完成后才会打包。完整 CBZ 使用 ZIP Store，避免对已有压缩图片再次压缩。

## 本地存储结构

```text
books/<32位十六进制书籍ID>/
    manifest.json            原始 Manifest 快照
    book.json                规范化书目快照
    cover.jpg                独立缓存的封面
    thumbs/
        000001.jpg           阅读器缩略图
        000002.jpg
    pages/                   部分下载时的散页
        000001.jpg
    book.cbz                 完整下载后的页面归档
    download-manifest.json   页面映射、校验和、状态和任务摘要
```

- 书籍 ID 与 URL、标题无关，保持稳定。
- 数据库只保存相对于书籍目录的路径。
- 封面和缩略图不计入“已下载页面”。
- 删除本地页面会删除 `pages/` 和 `book.cbz`，但保留书目、封面与缩略图。

## 书籍状态

| 状态 | 含义 |
| --- | --- |
| `online` | 仅保存书目和封面，页面来自远程 IIIF |
| `queued` | 下载任务排队中 |
| `downloading` | 正在下载 |
| `paused` | 任务暂停，本地页面保留 |
| `partial` | 部分页面已验证，仍有页面需要远程来源 |
| `offline` | 所有必需页面均已验证并保存在本地 |
| `error` | 最近任务失败，且没有可用的本地页面 |

应用重启时，正在运行的任务会变为暂停，未完成的页面状态会重置；已完成的页面会
重新校验。默认需要手动恢复，也可以设置 `MANNAZIA_AUTO_RESUME_DOWNLOADS=true`。

## 配置

所有应用变量使用 `MANNAZIA_` 前缀。常用配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MANNAZIA_PORT` | `8080` | Compose 发布的宿主机端口 |
| `PUID` / `PGID` | `1000` | 容器运行和文件归属的 UID / GID |
| `TZ` | `UTC` | 容器时区 |
| `MANNAZIA_LOG_LEVEL` | `INFO` | 日志级别 |
| `MANNAZIA_ALLOW_PRIVATE_NETWORKS` | `false` | 允许访问全部私网地址的开发开关 |
| `MANNAZIA_ALLOWED_PRIVATE_HOSTS` | 空 | 允许解析到私网的主机名，逗号分隔 |
| `MANNAZIA_DOWNLOAD_CONCURRENCY` | `3` | 页面下载并发数（1–16） |
| `MANNAZIA_DOWNLOAD_MAX_WIDTH` | `0` | 前三档的可选全局宽度上限；0 表示不额外限制 |
| `MANNAZIA_COVER_MAX_WIDTH` | `1200` | 导入时缓存封面的目标宽度 |
| `MANNAZIA_PAGE_THUMBNAILS_ENABLED` | `true` | 导入后缓存页面缩略图 |
| `MANNAZIA_THUMBNAIL_CONCURRENCY` | `4` | 缩略图并发数 |
| `MANNAZIA_DOWNLOAD_IMAGE_FORMAT` | `jpg` | 优先请求的 IIIF 图像格式 |
| `MANNAZIA_DOWNLOAD_RETRIES` | `3` | 瞬时失败重试次数 |
| `MANNAZIA_AUTO_RESUME_DOWNLOADS` | `false` | 重启后自动恢复被中断的任务 |
| `MANNAZIA_PREVIEW_TTL_SECONDS` | `900` | 导入预览缓存时间 |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | 信任的代理地址 |

完整配置和注释见 [`.env.example`](.env.example)。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/import/preview` | 预览 Manifest |
| `POST` | `/api/books` | 导入书籍 |
| `GET` | `/api/books` | 书目列表，支持搜索、状态和标签筛选 |
| `GET` | `/api/books/{id}` | 书籍详情 |
| `PATCH` | `/api/books/{id}` | 编辑书目元数据 |
| `DELETE` | `/api/books/{id}` | 删除书籍和全部本地文件 |
| `GET` | `/api/books/{id}/canvases` | 页面列表与服务信息 |
| `GET` | `/api/books/{id}/pages/{n}` | 本地页面或 CBZ 中的页面 |
| `GET` | `/api/books/{id}/thumbs/{n}` | 本地页面缩略图 |
| `GET` | `/api/books/{id}/cover` | 本地封面 |
| `GET/PUT` | `/api/books/{id}/progress` | 读取 / 保存阅读进度 |
| `POST` | `/api/books/{id}/downloads` | 创建下载任务，可传 `quality` |
| `GET` | `/api/downloads` | 下载任务列表 |
| `POST` | `/api/downloads/{id}/pause` | 暂停 |
| `POST` | `/api/downloads/{id}/resume` | 继续 |
| `POST` | `/api/downloads/{id}/cancel` | 取消并保留已完成页面 |
| `POST` | `/api/downloads/{id}/retry` | 重试失败页面 |
| `DELETE` | `/api/books/{id}/local-copy` | 删除本地页面，保留书目 |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/system/storage` | 存储占用 |

交互式 API 文档位于 `/api/docs`。

## 安全

Mannazia 默认阻止以下目标：

- 私网、回环、链路本地地址；
- 包含用户名或密码的 URL；
- 非 HTTP(S) 协议；
- 重定向降级和不安全的 DNS 解析结果。

如果 IIIF 服务位于局域网，请只加入精确主机名：

```dotenv
MANNAZIA_ALLOWED_PRIVATE_HOSTS=iiif.lan,library.local
```

项目**没有内置登录、权限或 TLS**。请放在带 HTTPS 和认证的反向代理之后，不要直接
暴露到公网。详细边界见下文的“已知限制”。

## 备份与升级

最简单且一致的备份方式是先停止容器：

```sh
docker compose stop
tar -czf mannazia-backup-$(date +%F).tar.gz config data books .env
docker compose start
```

需要同时备份 `data/` 和 `books/`：只有数据库会丢失页面，只有页面会丢失映射。

升级：

```sh
docker compose build
docker compose up -d
docker compose logs --tail=100 mannazia
```

数据库迁移在启动时自动运行。不要同时运行多个容器共享同一个 SQLite 数据库。

## 开发

需要 Python 3.12+、Node.js 22.12+（Docker 使用 Node 24）。

后端：

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: . .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
python -m pytest
ruff check app tests
ruff format --check app tests
```

运行 API（在仓库根目录）：

```sh
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8080
```

前端：

```sh
cd frontend
npm ci
npm run dev        # Vite :5173，代理 /api 到 :8080
npm run typecheck
npm run lint
npm test
npm run build      # 输出 frontend/dist
```

测试使用本地 fixture 和模拟 HTTP 客户端，不需要访问公共 IIIF 服务。当前测试规模：
后端 **97** 个，前端 **9** 个。

可选的演示数据脚本：`python backend/scripts/seed_demo.py`。它会写入当前配置指向的
`config/`、`data/` 和 `books/`，请勿对真实书库运行。

## 已知限制

- 仅保存每个 Canvas 的主图像；音频、视频、OCR、非绘制注释、多图层和复杂资源不支持。
- 只读取 Manifest 内嵌的绘制注释；外部 AnnotationPage 不会抓取。
- 研究档请求的是源站最大可用尺寸，不保证等于原始档案文件。
- 不支持 Manifest 刷新、Collection 导入、多用户、登录、TLS。
- 下载管理器是进程内任务；请使用单进程、单容器。
- 同一本书采用不同档位续传时，旧页面会保留原尺寸。
- CBZ 只在全部必需页面完成后生成；部分下载保留散页。
- 跨域瓦片受源站 CORS 限制；失败时会退回原图 URL。
- 自动封面选择可能选中扫描目标、条码或卷首图；暂不支持手动更换封面。
- 没有 OCR、全文检索、注释编辑或阅读列表；搜索覆盖书目元数据和标签。
- 仅支持浏览器可解码的 JPEG / PNG / WebP / GIF 页面；TIFF-only 源会标记为不支持。
- 中文界面不会翻译源数据中的标题、作者和权利文本。
- 字体文件较大且随应用分发；发布前请确认字体再分发权限，见 [`docs/FONTS.md`](docs/FONTS.md)。

## 文档

- [开发计划与实现记录](docs/PLAN.md)
- [字体与许可说明](docs/FONTS.md)
- [English README](README.en.md)

## 致谢

Mannazia 基于 IIIF Presentation API、IIIF Image API、FastAPI、SQLAlchemy/Alembic、
React、Vite 和 OpenSeadragon 构建。卢恩字符 **ᛗ**（Mannaz）作为项目的视觉符号，
不引申虚构的历史含义。

衬线字体使用 **Literata**（拉丁标题和编辑性文字）与 **Source Han Serif SC**
（中文标题和正文）。两种字体均为 SIL Open Font License 1.1，由应用本地提供，
不依赖第三方字体 CDN。

## 许可证

本项目采用 [MIT License](LICENSE)。Copyright (c) 2026 Mannazia contributors.
