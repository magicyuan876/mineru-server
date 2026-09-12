# AGENTS.md — MinerU Tianshu（天枢）

> 本文件面向 AI 编码代理，介绍本项目的架构、命令与开发约定。
> 项目文档、代码注释、日志输出以**简体中文**为主，修改现有文件时请保持中文注释风格。

## 项目概述

MinerU Tianshu（天枢）是一个**企业级 AI 数据预处理平台**，将非结构化数据转换为 AI 可用的结构化格式（Markdown + JSON）：

- 📄 文档：PDF、Word、Excel、PPT（MinerU 原生解析 DOCX/XLSX/PPTX；旧版 .doc/.xls/.ppt 经 LibreOffice 转换）、HTML/TXT/CSV/EPUB（MarkItDown）、ZIP 压缩包（自动解包为父子任务批量解析）
- 🖼️ 图片：JPG、PNG、BMP、TIFF（多 OCR 引擎 + 水印去除🧪）
- 🎙️ 音频：MP3、WAV、M4A、FLAC（SenseVoice 多语言、说话人识别、情感识别）
- 🎬 视频：MP4、AVI、MKV、MOV、WebM（FFmpeg 音频提取转写 + 关键帧 OCR🧪）
- 🧬 生物格式：FASTA、GenBank（插件化格式引擎）
- 🏗️ 企业特性：GPU 负载均衡、任务队列、JWT 认证、API Key、MCP 协议、RustFS 对象存储

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3、TypeScript、Vite、TailwindCSS、Pinia、Vue Router、vue-i18n（中英文） |
| 后端 | Python 3.12+、FastAPI、LitServe（GPU 负载均衡）、SQLite（任务队列/认证）、可选 Redis 队列 |
| AI 引擎 | MinerU 3.4+（pipeline/vlm/hybrid，含 vllm-mineru 远程模式）、SenseVoice/FunASR、MarkItDown |
| 基础设施 | Docker Compose、Nginx（前端）、RustFS（S3 兼容对象存储，minio-py 客户端）、MCP 协议 |
| 许可证 | Apache License 2.0 |

## 项目结构

```
mineru-tianshu/
├── frontend/                  # Vue 3 前端
│   ├── src/
│   │   ├── api/               # Axios API 客户端（authApi/taskApi/queueApi/systemApi）
│   │   ├── components/        # 组件（MarkdownViewer、JsonViewer、VirtualPdfViewer 等）
│   │   ├── views/             # 页面（Dashboard、TaskSubmit、TaskDetail、Login 等）
│   │   ├── stores/            # Pinia 状态（authStore、taskStore、queueStore 等）
│   │   ├── locales/           # i18n（zh-CN.ts、en-US.ts）
│   │   ├── router/            # Vue Router（含权限路由守卫）
│   │   └── types/ utils/      # TypeScript 类型与工具
│   ├── package.json  vite.config.ts  Dockerfile
│
├── backend/                   # Python 后端（所有服务共用此目录代码）
│   ├── start_all.py           # 统一启动脚本（本地开发入口）
│   ├── api_server.py          # FastAPI API 服务器（端口 8000）
│   ├── litserve_worker.py     # LitServe GPU Worker Pool（端口 8001）
│   ├── task_scheduler.py      # 任务调度器（超时重置、文件清理）
│   ├── mcp_server.py          # MCP 协议服务器（端口 8002，供 Claude Desktop 等调用）
│   ├── task_db.py             # SQLite 任务数据库（启动时原地迁移）
│   ├── redis_queue.py         # Redis 优先级队列（可选，SQLite 自动回退）
│   ├── download_models.py     # 模型预下载脚本
│   ├── auth/                  # JWT 认证、API Key、角色权限、OIDC/SAML SSO
│   ├── mineru_pipeline/       # MinerU 引擎封装
│   ├── audio_engines/         # SenseVoice 音频引擎
│   ├── video_engines/         # 视频引擎（FFmpeg + 关键帧提取，OCR 走 MinerU）
│   ├── format_engines/        # 插件化格式引擎（FASTA、GenBank 为参考实现）
│   ├── remove_watermark/      # 水印去除（YOLO11x + LaMa）
│   ├── image_caption/         # 图片描述（多模态大模型，OpenAI 兼容接口，配置存 system_config 表）
│   ├── output_normalizer/     # 输出标准化（统一 result.md/result.json/images/）
│   ├── storage/               # RustFS S3 客户端（图片上传、URL 替换）
│   ├── utils/                 # 工具函数
│   ├── requirements.txt       # Python 依赖（版本锁定，含 mineru[all]>=3.4.5）
│   └── Dockerfile  Dockerfile.cpu  Dockerfile.offline  install.sh
│
├── dify_plugin/tianshu/       # Dify 插件（manifest.yaml + provider/ + tools/）
├── setup.sh                   # 一键部署入口（交互式引导 + 非交互参数 --mode/--yes/--dry-run）
├── scripts/                   # 辅助脚本（docker-entrypoint.sh、init-models.sh）
├── docker-compose.yml         # 生产编排（GPU 版，含 vllm-mineru/rustfs 等）
├── docker-compose.dev.yml     # 开发编排（热重载 + debugpy 端口 5678）
├── docker-compose.cpu.yml     # CPU 本地开发（Mac Apple Silicon，需 Rosetta 2）
├── docker-compose.offline.yml # 离线部署编排
├── docker-compose.pipeline.yml# 纯 pipeline 模式部署
├── Makefile                   # Docker 快捷命令
├── pyproject.toml             # Ruff 配置（无 Python 打包用途）
├── .pre-commit-config.yaml    # pre-commit 钩子（唯一 CI 质量门禁）
└── .env.example               # 根环境变量模板（docker-compose 与 Makefile 消费）
```

## 构建与运行命令

### Docker 部署（主要路径）

```bash
make setup            # 首次部署：调用根目录 setup.sh（交互式引导）
make start | stop | restart | status | logs
make logs-worker      # 单服务日志（另有 logs-backend / logs-frontend）
make shell-worker     # 进入容器
make test-gpu         # 在 worker 容器内验证 torch CUDA
make validate         # docker compose config 校验
make dev              # 开发模式（docker-compose.dev.yml，热重载 + debugpy）
```

- 部署入口统一为根目录 `setup.sh`：`bash setup.sh`（交互菜单）或 `bash setup.sh --mode <gpu|pipeline|cpu|native|offline-build|offline-deploy|dev> [--gpus N] [--concurrency N] [--network cn|global] [--yes] [--dry-run]`；`--network` 决定 apt/pip/npm 镜像源（cn=国内镜像，global=官方源）。
- `make` 会读取根 `.env` 中的 `REDIS_QUEUE_ENABLED`，为 true 时自动附加 `--profile redis`。
- 离线部署：联网机 `bash setup.sh --mode offline-build` 构建离线包（产物 `docker-images/`）→ 传输 → 生产机 `bash setup.sh --mode offline-deploy`。
- CPU 本地开发（Mac）：`bash setup.sh --mode cpu`；Mac 原生运行（MPS 加速）：`bash setup.sh --mode native`。

### 本地后端开发

```bash
cd backend
pip install -r requirements.txt   # 或 bash install.sh（Linux/macOS 自动安装）
cp .env.example .env              # 必需！backend/.env 缺失时 start_all.py 直接退出
python start_all.py                          # API 8000 + Worker 8001 + Scheduler
python start_all.py --enable-mcp --mcp-port 8002
python start_all.py --accelerator cuda --devices 0,1 --workers-per-device 2
python start_all.py --accelerator cpu        # 无 GPU 环境
```

- 所有后端进程必须以 `backend/` 为工作目录运行（顶层导入：`from utils import ...`、`from auth import ...`）。
- 单独启动：`python api_server.py` / `python litserve_worker.py` / `python task_scheduler.py --enable-scheduler` / `python mcp_server.py`。

### 前端开发

```bash
cd frontend && npm install
npm run dev       # :3000，/api 代理到 localhost:8000（vite.config.ts）
npm run build     # tsc && vite build → dist/
```

### 服务端口（Docker 默认）

| 服务 | 端口 |
|---|---|
| 前端（Nginx） | 80 |
| API 服务器 | 8000（注意：`.env.example` 中 `API_PORT=8080`，调试连接失败时先确认实际值） |
| Worker | 8001 |
| MCP Server | 8002 |
| vLLM MinerU（手动 profile） | 30024 |

## 运行时架构

### 进程拓扑

`start_all.py` 以子进程方式启动各服务；Docker 中每个服务是独立容器，共用 `tianshu-backend` 镜像，通过 `scripts/docker-entrypoint.sh` 的角色参数（`api` / `worker` / `mcp`）区分。

### 拉取式任务队列

- API **从不直接调用 Worker**：写入 `tasks` 表后立即返回。
- Worker 在 `_worker_loop()` 中每 0.5 秒轮询 `TaskDB.get_next_task()` 主动拉取。
- 任务认领是原子的：`BEGIN IMMEDIATE` + `UPDATE ... WHERE task_id=? AND status='pending'`，`rowcount==0` 时重试（防止多 Worker 竞争）。
- `REDIS_QUEUE_ENABLED=true` 时优先走 `redis_queue.py`（有序集合优先级队列），SQLite 自动回退；无论哪种队列，**SQLite 始终是任务元数据与结果的唯一事实来源**。
- `task_db.py` 在启动时执行**原地 schema 迁移**：通过 `SELECT` 某列并捕获 `sqlite3.OperationalError` 来决定是否 `ALTER TABLE`。新增列必须用此模式，不能只改 `CREATE TABLE`（否则存量部署不会升级）。
- `auth/auth_db.py` 与任务库共用**同一个 SQLite 文件**（`DATABASE_PATH`）。

### 引擎路由（`litserve_worker.py::_process_task`）

单任务处理流水线：vLLM 容器互斥切换 → 旧版 Office 转换 → PDF 拆分 → 水印去除 → 引擎分发 → 输出标准化 → 持久化。

按任务的 `backend` 字段分发：

- `sensevoice` → 音频引擎；`video` → 视频引擎
- 包含 `pipeline` / `vlm-` / `hybrid-` → MinerU（`options["parse_mode"] = backend`）
- `auto` → 按扩展名嗅探：格式引擎 → 音频 → 视频 → MinerU（PDF/图片/DOCX/XLSX/PPTX） → 旧版 `.doc/.xls/.ppt` 经 LibreOffice 转换 → MarkItDown（HTML/TXT/CSV）兜底
- 其他 → 在 `FormatEngineRegistry` 中查找

**约定**：每个引擎都在 try/except 中导入并设置 `X_AVAILABLE` 标志，缺失的可选依赖只降级对应引擎，不会拖垮整个 Worker。新增引擎时请保持此模式。

`VLLMController.ensure_service()` 负责 **vLLM 容器互斥**（`tianshu-vllm-mineru`）：通过 Docker socket 停掉冲突容器以释放显存。

### 输出契约

- 每个引擎的原始输出目录都经过 `output_normalizer.normalize_output(dir, handle_method)`，统一为 `result.md` / `result.json` / `images/`；随后图片上传 RustFS 并把 Markdown/JSON 中的图片路径改写为公开 URL。
- `normalize_output` 支持可选 `image_processor` 回调，在本地规范化之后、RustFS 上传之前执行（此时图片引用仍是原始文件名，可精确匹配）。MinerU 路径用它实现**图片描述**：管理员在系统配置页开启并配置多模态大模型（OpenAI 兼容接口，配置存 `system_config` 表，`image_caption_*` 键，Worker 每次任务实时读取），`image_caption/` 模块并发调用模型为图片生成描述，写回 result.md 的图片 alt 与 result.json 的 `img_caption`；失败只降级不影响任务。api_key 接口返回掩码 `"********"`，发回掩码表示不修改。
- Worker 写入 `tasks.data` 列的 JSON 包含前端依赖的键：`pdf_path`（左侧 PDF 预览）、`json_content`（右侧版面渲染）、`markdown`、`markdown_file`。**重命名这些键会破坏 `TaskDetail.vue`**。

### 父子任务（PDF 分片 + ZIP 解包）

两类任务在 **Worker 中**拆分为父子任务（API 秒级响应），共用 `task_db.py` 的父子任务机制：`convert_to_parent_task` → N 个 `create_child_task`（子任务的 chunk_info 存在 options JSON 里）→ 子任务独立处理 → `on_child_task_completed` 在最后一个子任务完成时返回父 ID → `_merge_parent_task_results` 合并 Markdown/JSON。失败走 `on_child_task_failed`。

- **PDF 分片**：超过 `PDF_SPLIT_THRESHOLD_PAGES`（默认 500 页）时按 `PDF_SPLIT_CHUNK_SIZE` 页切分，分片存 `output_dir/splits/{task_id}/`，chunk_info 为 `{start_page, end_page, page_count}`，合并时按页序拼接并修正 page_idx 偏移。
- **ZIP 解包**：`.zip` 任务在引擎路由前由 `_should_split_zip` 解包（任何 backend 值都走拆分，子任务继承父任务 backend），安全限制：最多 200 个条目、解压总大小上限 2GB（防 zip bomb），跳过目录、`__MACOSX`/隐藏文件、嵌套 zip 与非白名单格式；解压文件同样存 `output_dir/splits/{task_id}/`，chunk_info 为 `{index, entry_name}`，合并时按 index 排序并在每段 Markdown 前加 `## {entry_name}` 章节头。
- **防重入**：`_process_task` 开头会跳过 `is_parent` 且已有子任务的任务（调度器 `reset_stale_tasks` 可能把超时的父任务打回 pending 被重复拉取）。

### 格式引擎插件系统

新增文档格式：继承 `backend/format_engines/base.py` 的 `FormatEngine`，设置 `SUPPORTED_EXTENSIONS` / `FORMAT_NAME` / `FORMAT_DESCRIPTION`，实现 `parse()` 返回 `{format, markdown, json_content, metadata, summary}`，然后在 `format_engines/__init__.py` 中注册。注册后同时支持显式 `backend` 值和 `auto` 检测，并出现在 `GET /api/v1/engines` 中。FASTA 和 GenBank 是参考实现。

### 认证

- JWT（Access + Refresh Token）或 API Key，由 `auth/dependencies.py::get_current_user` 解析（先试 Bearer Token，再试 API Key）。
- 授权使用 `require_permission(...)` / `require_role(...)` 依赖工厂。
- 任务带 `user_id`，非管理员只能看到自己的任务。
- OIDC / SAML SSO 在 `auth/sso.py`，按配置条件注册。

### API 概览

`api_server.py` 提供 `/api/v1/*`（任务提交/查询/取消/重试/暂停/恢复/清缓存、队列统计、管理员清理与超时重置、`/engines`、`/health`、文件服务），认证路由在 `/api/v1/auth/*`。交互文档：`http://localhost:8000/docs`（前端内嵌 Scalar 版 ApiDocsScalar.vue）。文件服务端点会校验路径 `is_relative_to(OUTPUT_DIR)`，新增接收路径的端点必须保留此防护。

## 配置

**两个独立的 `.env` 文件，不要混淆：**

- **根目录 `.env`**（由 `.env.example` 复制）—— docker-compose 与 Makefile 消费：端口、`GPU_COUNT`、`MAX_CONCURRENT_TASKS`（Worker 并发唯一控制入口）、`WORKER_MEMORY_LIMIT/RESERVATION`、`JWT_SECRET_KEY`、`DATABASE_PATH`、`PDF_SPLIT_*`、`RUSTFS_*`、`REDIS_*`、`VITE_API_BASE_URL`。
- **`backend/.env`**（由 `backend/.env.example` 复制）—— 本地开发 `start_all.py` 必需。

关键环境变量注意事项：

- `MAX_CONCURRENT_TASKS > 1` 时必须显式设置 `MINERU_VIRTUAL_VRAM_SIZE = 单卡显存 / MAX_CONCURRENT_TASKS`，否则每个 Worker 进程都按整卡规划 batch → CUDA OOM。
- `WORKER_MEMORY_LIMIT` 需随进程数放大（约每进程 8G），`setup.sh` 会自动计算。
- `RUSTFS_ENABLED=true` 时 `RUSTFS_PUBLIC_URL` 必须为浏览器可达的完整 URL；RustFS 端口仅绑定宿主机回环（127.0.0.1），图片默认经前端 nginx `/s3/` 路径反代（如 `http://<服务器IP>/s3`）。
- 后端容器以非 root 用户 `tianshu`（UID 10001）运行，挂载到 `/app/data`、`/app/logs` 的宿主机目录必须对其可写（`setup.sh` 的 `create_directories` 会做 best-effort `chmod`）；Worker 例外，因挂载 `/var/run/docker.sock` 在 compose 中保持 `user: root`。
- 全新部署必须设置 `TIANSHU_ADMIN_PASSWORD`（可选 `TIANSHU_ADMIN_USERNAME`，默认 admin），否则 API 服务拒绝启动；`setup.sh` 会自动生成随机密码写入 `.env`。
- 模型权重在 `models/`，运行时数据在 `data/{uploads,output,db}`，日志在 `logs/{backend,worker,mcp}`。

## 代码风格

### Python（backend/）

- 目标版本 Python 3.12，行宽 120，双引号（Ruff 配置见 `pyproject.toml`）。
- Ruff 只启用关键检查：`select = ["E", "F"]`，`ignore = ["E402", "E501"]`。
- 注释与日志使用简体中文，与现有文件保持一致。
- 注释只解释"为什么"，不复述代码行为；不新增解释本次改动的注释。

### 前端

- TypeScript 严格模式；路径别名 `@` → `src/`。
- 组件使用 Vue 3 Composition API（`<script setup>`）；状态走 Pinia store；文案走 vue-i18n（zh-CN / en-US 双语言，新增文案需同步两个语言文件）。
- 无独立 lint 配置，遵循现有代码风格。

### 通用

- 行尾统一 LF（`.bat/.cmd/.ps1` 除外）；文件以换行符结尾；无行尾空格。
- Markdown 使用 markdownlint（禁用 MD013 行长限制）。

## 测试策略

**本项目没有自动化测试套件**（无 pytest、无前端单测）。质量门禁是 pre-commit，也是唯一的 CI 任务（`.github/workflows/pylint.yml`，GitHub Actions 中实际运行的是 pre-commit action）：

```bash
pip install pre-commit && pre-commit install
pre-commit run --all-files          # 全量检查
ruff format backend/ && ruff check --fix backend/   # 手动跑 Python 检查
```

pre-commit 钩子包含：基础文件检查（大文件 >5MB、私钥、冲突标记）、Ruff format/lint（仅 `backend/*.py`）、shellcheck（排除含中文的两个脚本）、markdownlint、LF 行尾统一。

功能验证方式：`make test-gpu`（容器内验证 CUDA）、`make test-api`（curl 健康检查），以及通过前端页面/API 手动跑通端到端流程。

## 安全注意事项

- **JWT_SECRET_KEY** 生产环境必须改为随机字符串：`openssl rand -hex 32`。
- `.env` 文件含密钥，已 gitignore，**不要提交或读取后外泄**；示例配置请提交到 `.env.example`。
- RustFS 无默认凭据：`RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` 必须显式设置（compose 用 `:?` 强制，`setup.sh` 自动生成随机值）。
- API Key 认证与 JWT 并存，新增端点记得挂 `get_current_user` / 权限依赖。
- 文件服务端点必须保留路径逃逸防护（`is_relative_to(OUTPUT_DIR)`）。
- pre-commit 会检查私钥与 >5MB 大文件。
- Worker 容器挂载了 `/var/run/docker.sock`（用于 vLLM 容器互斥控制），改动相关逻辑时注意其权限敏感性。

## 其他模块

- **Dify 插件**（`dify_plugin/tianshu/`）：将天枢封装为 Dify 工具（解析文档 + 自动轮询结果），Python 3.12，独立于后端代码，有自己的 `requirements.txt`。
- **MCP Server**：支持工具 `parse_document`、`get_task_status`、`list_tasks`、`get_queue_stats`；配置示例见 `mcp_config.example.json`，详细指南见 `backend/MCP_GUIDE.md`。

## 参考文档

- `README.md` / `README_EN.md` — 项目总览（含更新日志）
- `backend/README.md` — 后端 API 详细说明
- `CLAUDE.md` — 面向 Claude Code 的架构与命令指南（内容与本文件互补）
- `docs/img/` — 界面截图；`SPEAKER_DIARIZATION_IMPLEMENTATION.md` — 说话人识别实现说明
- 各引擎目录下的 `README.md`（`backend/video_engines/`、`backend/format_engines/`、`backend/remove_watermark/`）
