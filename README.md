<div align="center">

# Tianshu 天枢

**企业级 AI 数据预处理平台**

支持文档、图片、音频等多模态数据处理 | GPU 加速 | MCP 协议

结合 Vue 3 前端 + FastAPI 后端 + LitServe GPU负载均衡

<p>
  <a href="https://github.com/magicyuan876/mineru-tianshu/stargazers">
    <img src="https://img.shields.io/github/stars/magicyuan876/mineru-tianshu?style=for-the-badge&logo=github&color=yellow" alt="Stars"/>
  </a>
  <a href="https://github.com/magicyuan876/mineru-tianshu/network/members">
    <img src="https://img.shields.io/github/forks/magicyuan876/mineru-tianshu?style=for-the-badge&logo=github&color=blue" alt="Forks"/>
  </a>
  <a href="https://github.com/magicyuan876/mineru-tianshu/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-Apache%202.0-green?style=for-the-badge" alt="License"/>
  </a>
</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Vue-3.x-green?logo=vue.js&logoColor=white" alt="Vue"/>
  <img src="https://img.shields.io/badge/FastAPI-0.115+-teal?logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/CUDA-Supported-76B900?logo=nvidia&logoColor=white" alt="CUDA"/>
  <img src="https://img.shields.io/badge/MCP-Supported-orange" alt="MCP"/>
</p>

[![Verified on MseeP](https://mseep.ai/badge.svg)](https://mseep.ai/app/819ff68b-5154-4717-9361-7db787d5a2f8)

[English](./README_EN.md) | 简体中文

<p>
  <a href="https://github.com/magicyuan876/mineru-tianshu">
    <img src="https://img.shields.io/badge/⭐_Star-项目-yellow?style=for-the-badge&logo=github" alt="Star"/>
  </a>
</p>

**如果这个项目对你有帮助，请点击右上角 ⭐ Star 支持一下，这是对开发者最大的鼓励！**

</div>

---

## 📝 最新更新

### 2026-09-11 🚀 MinerU 3.4.5 升级

- ✅ **MinerU 3.4.5 升级**：`mineru[all]>=3.4.5`，同步 `mineru-vl-utils>=1.0.5,<2`、`pypdf>=5.6.0`
- ✅ **VLM 模型更新**：`MinerU2.5-2509-1.2B` → `MinerU2.5-Pro-2605-1.2B`（模型下载脚本、`mineru.json`、vLLM 服务同步）
- ✅ **兼容确认**：`do_parse` API、`vlm/hybrid` 后端名（旧别名 `*-auto-engine` 仍受支持）、pipeline 模型目录结构（PP-DocLayoutV2 等）均保持不变
- ✅ **macOS 原生支持**：Apple Silicon 自动启用 MPS 加速（`--accelerator mps`），VLM 后端自动走 MLX；音视频辅助引擎在 mac 上回退 CPU

### 2026-04-12 🔧 MinerU 3.0.9 升级 & Office 格式增强

- ✅ **MinerU 3.0.9 升级**
  - 核心依赖同步：`transformers==4.57.6`、`albumentations>=1.4.11`
  - 配置格式迁移：`magic-pdf.json`（扁平）→ `mineru.json`（嵌套 `models-dir` 结构）
  - 模型路径适配 3.0 新结构（`unimernet_hf_small_2503`、`pp_formulanet_plus_m`）
- ✅ **DOCX 原生解析**：`.docx` 文件路由至 MinerU 3.0 原生解析器（`office_docx_analyze`），解析精度优于 MarkItDown
- ✅ **旧版 Office 格式支持**：`.doc`、`.xls`、`.ppt` 经 LibreOffice 自动转换为新格式后，再交由 MinerU 或 MarkItDown 处理，不再报错
- ✅ **前端引擎信息面板**：仪表盘新增引擎状态卡片，实时展示各引擎版本号、GPU/CUDA 环境及关键包版本

### 2025-12-10 ⚡ 大文件并行处理

- ✅ **PDF 自动拆分功能**：超过阈值（默认 500 页）的 PDF 自动拆分为多个子任务并行处理
  - 可配置的分块大小（默认 500 页/块），显著提升大文件处理速度
  - 实现父子任务系统：自动管理子任务状态并在完成后合并结果
  - 智能结果合并：保留原始页码信息，按序合并 Markdown 和 JSON 输出
  - 处理时间可缩短 40-60%（取决于硬件配置）
  - **异步拆分**：拆分操作在 Worker 中进行，API 接口秒级响应
- ✅ **PDF 拆分配置**（`.env` 新增）
  - `PDF_SPLIT_ENABLED`: 是否启用自动拆分（默认 `true`）
  - `PDF_SPLIT_THRESHOLD_PAGES`: 拆分阈值页数（默认 `500`）
  - `PDF_SPLIT_CHUNK_SIZE`: 每个子任务处理页数（默认 `500`）
- ✅ **Worker 内存管理**
  - `WORKER_MEMORY_LIMIT`: 容器硬内存限制（默认 `16G`）
  - `WORKER_MEMORY_RESERVATION`: 内存软限制/预留（默认 `8G`）

### 2025-12-05 🗄️ RustFS 对象存储集成

- ✅ **RustFS 对象存储**：所有解析结果的图片自动上传到对象存储
  - S3 兼容 API，基于 minio-py 实现
  - 批量上传图片，自动生成公开访问 URL
  - 短且唯一的文件名生成（时间戳 Base62 + NanoID）
  - 按日期自动分组（YYYYMMDD/文件名.ext）
  - Markdown/JSON 中的图片路径自动替换为对象存储 URL
  - Docker Compose 一键部署 RustFS 服务
  - 需配置 `RUSTFS_PUBLIC_URL` 环境变量（外部可访问地址）
- ✅ **输出标准化优化**：改进图片路径处理，统一使用对象存储 URL
- ✅ **配置简化**：精简 `.env.example` 配置文件，移除冗余选项

### 2025-11-12 📦 代码优化与文档整理

- ✅ **输出标准化**：统一 Markdown/JSON 输出格式，优化图片路径处理
- ✅ **文档精简**：精简 README 文档，移除冗余说明文件，保持项目整洁
- ✅ **代码质量**：优化错误处理，改进日志输出，提升系统稳定性

### 2025-10-30 🐳 Docker 部署 + 企业级认证系统

- ✅ **Docker 容器化部署支持**
  - **一键部署**：根目录交互式脚本 `setup.sh`（或 `make setup`）即可完成全栈部署
  - **多阶段构建**：优化镜像体积，分离依赖层和应用层
  - **GPU 支持**：NVIDIA CUDA 12.6 + Container Toolkit 集成
  - **服务编排**：前端、后端、Worker、MCP 完整编排（docker-compose）
  - **开发友好**：支持热重载、远程调试（debugpy）、实时日志
  - **生产就绪**：健康检查、数据持久化、零停机部署、资源限制
  - **多种部署模式**：GPU 标准、纯 pipeline、Mac CPU 本地开发、离线部署、开发热重载
  - 详见：Docker 配置文件（`docker-compose.yml`、`backend/Dockerfile`、`frontend/Dockerfile`）

- ✅ **企业级用户认证与授权系统**
  - **JWT 认证**：安全的 Token 认证机制，支持 Access Token 和 Refresh Token
  - **用户数据隔离**：每个用户只能访问和管理自己的任务数据
  - **角色权限**：管理员（admin）和普通用户（user）角色
  - **API Key 管理**：用户可自助生成和管理 API 密钥，用于第三方集成
  - **用户管理**：管理员可管理所有用户、重置密码、启用/禁用账户
  - **SSO 预留接口**：支持 OIDC 和 SAML 2.0 单点登录（可选配置）
  - **前端集成**：登录/注册页面、用户中心、权限路由守卫
  - **数据库迁移**：自动为现有数据创建默认用户
  - 详见：`backend/auth/` 目录

### 2025-10-29 🧬 生物信息学格式支持

- ✅ **新增插件化格式引擎系统**
  - 支持专业领域文档格式的解析和结构化
  - 统一的引擎接口，易于扩展新格式
  - 为 RAG 应用提供 Markdown 和 JSON 双格式输出

- ✅ **生物信息学格式引擎**
  - **FASTA 格式**：DNA/RNA/蛋白质序列解析
    - 序列统计（数量、长度、平均值）
    - 碱基组成分析（A/T/G/C 比例）
    - 序列类型自动检测（DNA/RNA/蛋白质）
  - **GenBank 格式**：NCBI 基因序列注释格式
    - 完整的注释信息提取
    - 特征类型统计（gene/CDS/mRNA 等）
    - GC 含量计算和生物物种信息
  - 支持 BioPython 或内置解析器（可选依赖）
  - 详见：`backend/format_engines/README.md`

### 2025-10-27 🎨 水印去除支持（🧪 实验性）

- ✅ **智能水印检测与去除**
  - YOLO11x 专用检测模型 + LaMa 高质量修复
  - 支持图片（PNG/JPG/JPEG 等）和 PDF（可编辑/扫描件）
  - 前端可调参数：检测置信度、去除范围
  - 自动保存调试文件（检测可视化、掩码等）
  - 轻量模型，处理速度快，显存占用低

> **⚠️ 实验性功能**：某些特殊水印可能效果不佳，建议先小范围测试。  
> 📖 **详细说明**：[水印去除优化指南](backend/remove_watermark/README.md)

### 2025-10-24 🎬 视频处理支持

- ✅ **新增视频处理引擎**
  - 支持 MP4、AVI、MKV、MOV、WebM 等主流视频格式
  - **音频转写**：从视频中提取音频并转写为文字（基于 FFmpeg + SenseVoice）
  - **关键帧 OCR（🧪 实验性）**：自动提取视频关键帧并进行 OCR 识别
    - 场景检测：基于帧差异的自适应场景变化检测
    - 质量过滤：拉普拉斯方差 + 亮度评估
    - 图像去重：感知哈希（pHash）+ 汉明距离
    - 文本去重：编辑距离算法避免重复内容
    - 支持 PaddleOCR-VL 引擎
  - 支持多语言识别、说话人识别、情感识别
  - 输出带时间戳的文字稿（JSON 和 Markdown 格式）
  - 详见：`backend/video_engines/README.md`

### 2025-10-23 🎙️ 音频处理引擎

- ✅ **新增 SenseVoice 音频识别引擎**
  - 支持多语言识别（中文/英文/日文/韩文/粤语）
  - 内置说话人识别（Speaker Diarization）
  - 情感识别（中性/开心/生气/悲伤）
  - 输出 JSON 和 Markdown 格式
  - 详见：`backend/audio_engines/README.md`

### 2025-10-23 ✨

**🎯 支持内容结构化 JSON 格式输出**

- MinerU (pipeline) 和 PaddleOCR-VL 引擎现在支持输出结构化的 JSON 格式
- JSON 输出包含完整的文档内容结构信息（页面、段落、表格等）
- 用户可在任务详情页面切换查看 Markdown 或 JSON 格式
- 前端提供交互式 JSON 查看器，支持展开/收起、复制、下载等功能

**🎉 新增 PaddleOCR-VL 多语言 OCR 引擎**

- 支持 109+ 语言自动识别，无需手动指定语言
- 文档方向分类、文本图像矫正、版面区域检测等增强功能
- 原生 PDF 多页文档支持，模型自动下载管理

---

## 🌟 项目简介

MinerU Tianshu（天枢）是一个**企业级 AI 数据预处理平台**，将非结构化数据转换为 AI 可用的结构化格式：

- **📄 文档**: PDF、Word、Excel、PPT → Markdown/JSON（MinerU、水印去除🧪）
- **🎬 视频**: MP4、AVI、MKV → 语音转写 + 关键帧 OCR🧪（FFmpeg + SenseVoice）
- **🎙️ 音频**: MP3、WAV、M4A → 文字转写 + 说话人识别（SenseVoice 多语言）
- **🖼️ 图片**: JPG、PNG → 文字提取 + 结构化（多 OCR 引擎 + 水印去除🧪）
- **🧬 生物格式**: FASTA、GenBank → Markdown/JSON（插件化引擎，易扩展）
- **🏗️ 企业特性**: GPU 负载均衡、任务队列、JWT 认证、MCP 协议、现代化 Web 界面

## 📸 功能展示

<div align="center">

### 📊 仪表盘 - 实时监控

<img src="./docs/img/dashboard.png" alt="仪表盘" width="80%"/>

*实时监控队列统计和最近任务*

---

### 📤 任务提交 - 文件拖拽上传

<img src="./docs/img/submit.png" alt="任务提交" width="80%"/>

*支持批量处理和高级配置*

---

### ⚙️ 队列管理 - 系统监控

<img src="./docs/img/tasks.png" alt="队列管理" width="80%"/>

*重置超时任务、清理旧文件*

</div>

### 主要功能

- ✅ **用户认证**: JWT 认证、角色权限、API Key 管理
- ✅ **任务管理**: 拖拽上传、批量处理、实时追踪、Markdown/JSON 预览
- ✅ **队列管理**: 系统监控、超时重置、文件清理
- ✅ **MCP 协议**: AI 助手（Claude Desktop）无缝集成
- ✅ **Docker 部署**: 一键部署、GPU 支持、完整容器化

### 支持的文件格式

- 📄 **文档**: PDF、Word、Excel、PPT（MinerU、MarkItDown）
- 🖼️ **图片**: JPG、PNG、BMP、TIFF（MinerU）
- 🎙️ **音频**: MP3、WAV、M4A、FLAC（SenseVoice 多语言、说话人识别、情感识别）
- 🎬 **视频**: MP4、AVI、MKV、MOV、WebM（音频转写 + 关键帧 OCR🧪）
- 🧬 **生物格式**: FASTA、GenBank（序列统计、碱基分析、GC 含量）
- 🌐 **其他**: HTML、Markdown、TXT、CSV

## 🏗️ 项目结构

```
mineru-server/
├── frontend/              # Vue 3 前端（TypeScript + TailwindCSS）
│   ├── src/               # 源码（api、components、views、stores、router）
│   └── vite.config.ts
│
├── backend/               # Python 后端（FastAPI + LitServe）
│   ├── api_server.py      # API 服务器
│   ├── litserve_worker.py # GPU Worker Pool
│   ├── mcp_server.py      # MCP 协议服务器
│   ├── auth/              # 认证授权（JWT、SSO）
│   ├── audio_engines/     # 音频引擎（SenseVoice）
│   ├── video_engines/     # 视频引擎（FFmpeg + OCR）
│   ├── format_engines/    # 格式引擎（FASTA、GenBank）
│   ├── remove_watermark/  # 水印去除（YOLO11x + LaMa）
│   └── requirements.txt
│
├── setup.sh               # 一键部署脚本（交互式引导 + 非交互参数）
├── scripts/               # 辅助脚本（docker-entrypoint.sh、init-models.sh）
│
├── docker-compose.yml     # Docker 编排配置
└── Makefile               # 快捷命令
```

## 🚀 快速开始

### 方式一：Docker 部署（⭐ 推荐）

**前置要求**：Docker 20.10+、Docker Compose 2.0+、NVIDIA Container Toolkit（GPU 可选）

```bash
# 一键部署（交互式引导）
bash setup.sh

# 跳过提问直接部署（非交互，适合 CI/熟手）
bash setup.sh --mode pipeline --yes

# 预览将要执行的配置（不构建、不启动）
bash setup.sh --mode gpu --dry-run
```

> Windows 用户请使用 Git Bash 或 WSL 运行 `setup.sh`。

`setup.sh` 支持六种部署模式：

| 模式 | 说明 |
|---|---|
| `gpu` | GPU 标准部署（docker-compose.yml，默认） |
| `pipeline` | 纯 pipeline 部署（只下载 PDF-Extract-Kit 模型，更轻量） |
| `cpu` | Mac CPU 本地开发（docker-compose.cpu.yml + .env.cpu） |
| `native` | 本机原生部署（不用 Docker，Apple Silicon 自动 MPS 加速，VLM 走 MLX） |
| `offline-build` / `offline-deploy` | 离线部署：联网机构建离线包 / 生产机离线部署 |
| `dev` | 开发模式（docker-compose.dev.yml，热重载 + debugpy） |

交互过程会询问网络环境（国内镜像加速 / 海外官方源直连）、GPU 数量（自动检测）、Worker 并发数、模型源（HuggingFace/ModelScope）、Redis、RustFS 公网地址和端口，并自动完成 JWT 密钥生成、`MINERU_VIRTUAL_VRAM_SIZE`/`WORKER_MEMORY_LIMIT` 计算、目录创建和健康检查。

> 网络环境也可用参数指定：`--network cn`（国内镜像加速，默认）或 `--network global`（海外/代理，官方源直连）。该选择同时作用于 Docker 镜像构建（apt/pip/npm 源）与原生部署的 pip 安装。

常用命令：

```bash
make start    # 启动服务
make stop     # 停止服务
make logs     # 查看日志
```

**服务访问**：
- 前端：http://localhost:80
- API 文档：http://localhost:8000/docs
- Worker：http://localhost:8001
- MCP：http://localhost:8002

---

### 方式二：本地开发部署

**前置要求**：Node.js 18+、Python 3.8+、CUDA（可选）

**1. 安装依赖**

```bash
cd backend
bash install.sh              # Linux/macOS 自动安装
# 或 pip install -r requirements.txt
```

**2. 启动后端**

```bash
cd backend
python start_all.py          # 启动所有服务
python start_all.py --enable-mcp  # 启用 MCP 协议
```

**3. 启动前端**

```bash
cd frontend
npm install
npm run dev                  # http://localhost:3000
```

## 📖 使用指南

### 提交任务

1. 点击"提交任务"，拖拽上传文件（支持批量）
2. 配置选项：选择引擎（pipeline/vlm）、语言、公式/表格识别、优先级
3. 提交后在仪表盘或任务列表查看状态
4. 完成后预览/下载 Markdown 或 JSON 结果

### 引擎选择

- **pipeline**: MinerU 标准流程，通用文档解析
- **vlm-transformers/vlm-vllm-engine**: MinerU VLM 模式
<!-- - **deepseek-ocr**: DeepSeek OCR，高精度需求 -->

## 🎯 核心特性

- **Worker 主动拉取**: 0.5秒响应，无需调度器触发
- **GPU 负载均衡**: LitServe 自动调度，避免显存冲突，多 GPU 隔离
- **并发安全**: 原子操作防止任务重复，支持多 Worker 并发
- **多解析引擎**: MinerU、MarkItDown、格式引擎
- **自动清理**: 定期清理旧文件，保留数据库记录
- **现代化 UI**: TailwindCSS 美观界面，响应式设计，实时更新

## ⚙️ 配置说明

### 后端配置

```bash
# 自定义启动
python backend/start_all.py \
  --api-port 8000 \
  --worker-port 9000 \
  --accelerator cuda \
  --devices 0,1 \
  --workers-per-device 2 \
  --enable-mcp --mcp-port 8002
```

详见 [backend/README.md](backend/README.md)

### MCP 协议集成

MinerU Tianshu 支持 **Model Context Protocol (MCP)**，让 AI 助手（Claude Desktop）直接调用文档解析服务。

**1. 启动服务**

```bash
cd backend
python start_all.py --enable-mcp  # MCP Server 端口 8002（默认）
```

**2. 配置 Claude Desktop**

编辑配置文件（`%APPDATA%\Claude\claude_desktop_config.json` Windows / `~/Library/Application Support/Claude/claude_desktop_config.json` macOS）：

```json
{
  "mcpServers": {
    "mineru-tianshu": {
      "url": "http://localhost:8002/sse",
      "transport": "sse"
    }
  }
}
```

> **注意**：MCP Server 默认端口为 8002（本地和 Docker 部署均相同）

**3. 使用**

在 Claude 中直接说：`帮我解析这个 PDF：C:/Users/user/doc.pdf`

**支持的工具**：
- `parse_document`: 解析文档（Base64 或 URL，最大 500MB）
- `get_task_status`: 查询任务状态
- `list_tasks`: 列出最近任务
- `get_queue_stats`: 获取队列统计

详见 [backend/MCP_GUIDE.md](backend/MCP_GUIDE.md)

## 🚢 生产部署

### 离线部署

Tianshu 支持**完全离线部署**，分为联网机构建、生产机部署两个阶段：

```bash
# 1. 在联网环境构建离线包（Linux/Mac 均可，产物在 docker-images/）
bash setup.sh --mode offline-build

# 2. 传输到生产服务器
rsync -avz docker-images/ user@prod-server:/opt/tianshu/

# 3. 在生产服务器部署
cd /opt/tianshu
bash setup.sh --mode offline-deploy
```

**特点**：
- ✅ **跨平台构建**：支持在 Mac（Apple Silicon/Intel）构建 Linux amd64 镜像
- ✅ **完全离线**：所有模型（~15GB）和依赖预先打包
- ✅ **一键部署**：自动配置环境变量、JWT 密钥、RustFS 对象存储
- ✅ **Office 文档支持**：MinerU 原生解析 .docx/.xlsx/.pptx，旧版 .doc/.xls/.ppt 经 LibreOffice 转换后解析

**关键修复**：
- 🔧 Worker uploads 目录读写权限
- 🔧 albumentations/albucore 版本锁定（解决 MinerU 公式识别依赖）
- 🔧 RustFS 镜像平台指定（确保 amd64 架构一致性）

### 在线 Docker 部署

```bash
# 交互式引导部署（推荐）
bash setup.sh

# 或直接启动（需已配置 .env）
docker compose up -d
```

### 手动部署

如需手动部署：

**前端构建**：`cd frontend && npm run build`（产物在 `dist/`）

**Nginx 配置**：
```nginx
server {
    listen 80;
    root /path/to/frontend/dist;
    location / { try_files $uri $uri/ /index.html; }
    location /api/ { proxy_pass http://localhost:8000/api/; }
}
```

**后端部署**：`cd backend && python start_all.py --api-port 8000 --worker-port 9000`

### 附录：常用 Docker 命令速查

```bash
# 构建与启动
docker compose build --parallel        # 并行构建全部镜像
docker compose up -d                   # 后台启动全部服务
docker compose down                    # 停止并移除容器

# 状态与日志
docker compose ps                      # 查看服务状态
docker compose logs -f                 # 跟踪全部日志
docker compose logs -f backend         # 跟踪单服务日志

# 进入容器与调试
docker compose exec backend bash       # 进入后端容器
docker compose exec worker nvidia-smi  # 检查容器内 GPU
docker stats                           # 查看容器资源占用
```

## 📚 技术栈

**前端**：Vue 3、TypeScript、Vite、TailwindCSS、Pinia、Vue Router

**后端**：FastAPI、LitServe、MinerU、SenseVoice、SQLite、Loguru

## 🔧 故障排查

**前端无法连接**：`curl http://localhost:8000/api/v1/health` 检查后端，查看 `vite.config.ts` 代理配置

**Worker 无法启动**：`nvidia-smi` 检查 GPU，`pip list | grep mineru` 检查依赖

详见 [frontend/README.md](frontend/README.md) 和 [backend/README.md](backend/README.md)

## 📄 API 文档

访问 <http://localhost:8000/docs> 查看完整 API 文档

主要端点：
- `POST /api/v1/tasks/submit` - 提交任务
- `GET /api/v1/tasks/{task_id}` - 查询状态
- `GET /api/v1/queue/stats` - 队列统计

## 🤝 贡献

欢迎提交 Issue 和 Pull Request!

## 🙏 鸣谢

本项目基于以下优秀的开源项目构建：

**核心引擎**

- [MinerU](https://github.com/opendatalab/MinerU) - PDF/图片文档解析
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) - 语音识别与说话人识别
- [FunASR](https://github.com/modelscope/FunASR) - 语音识别框架
- [MarkItDown](https://github.com/microsoft/markitdown) - 文档转换工具

**框架与工具**

- [LitServe](https://github.com/Lightning-AI/LitServe) - GPU 负载均衡
- [FastAPI](https://fastapi.tiangolo.com/) - 后端 Web 框架
- [Vue.js](https://vuejs.org/) - 前端框架
- [TailwindCSS](https://tailwindcss.com/) - CSS 框架
- [PyTorch](https://pytorch.org/) - 深度学习框架

感谢所有开源贡献者！

## 📜 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源协议。

```
Copyright 2024 MinerU Tianshu Contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

<div align="center">

**天枢 (Tianshu)** - 企业级多 GPU 文档解析服务 ⚡️

*北斗第一星，寓意核心调度能力*

<br/>

### 喜欢这个项目？

<a href="https://github.com/magicyuan876/mineru-tianshu/stargazers">
  <img src="https://img.shields.io/github/stars/magicyuan876/mineru-tianshu?style=social" alt="Stars"/>
</a>
<a href="https://github.com/magicyuan876/mineru-tianshu/network/members">
  <img src="https://img.shields.io/github/forks/magicyuan876/mineru-tianshu?style=social" alt="Forks"/>
</a>

**点击 ⭐ Star 支持项目发展，感谢！**

</div>
