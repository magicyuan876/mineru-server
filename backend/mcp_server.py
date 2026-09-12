"""
MinerU Tianshu - MCP Server
天枢 MCP 协议服务器

企业级 AI 数据预处理平台 - MCP 接口
通过 Model Context Protocol 暴露数据处理能力

支持功能:
- 文档、图片、音频、视频等多模态数据处理
- Base64 编码的文件传输
- URL 文件下载
- 异步任务处理和状态查询
- 队列统计和任务管理
"""

import asyncio
import base64
import hmac
import ipaddress
import json
import os
import re
import socket
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
import uvicorn
from loguru import logger
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from utils import FilenameValidationError, ensure_within_directory, sanitize_filename

# 文件大小限制（从环境变量读取，0 表示不限制）
MAX_FILE_SIZE_BYTES = int(os.getenv("MAX_FILE_SIZE", "0"))  # 0 = 不限制
MAX_FILE_SIZE_MB = MAX_FILE_SIZE_BYTES / (1024 * 1024) if MAX_FILE_SIZE_BYTES > 0 else 0

# URL 下载响应体上限（流式读取超限即中止，防止内存被打爆）
MAX_DOWNLOAD_SIZE_BYTES = 200 * 1024 * 1024

# API 配置（从环境变量读取）
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# MCP 访问后端 API 的服务凭据（API 开启认证后必须配置，否则后端接口一律 401）
TIANSHU_API_KEY = os.getenv("TIANSHU_API_KEY", "")

# MCP 服务自身的访问密钥（逗号分隔），/sse 与 /messages 强制校验；为空时拒绝一切请求
MCP_API_KEYS = [key.strip() for key in os.getenv("MCP_API_KEYS", "").split(",") if key.strip()]


def _api_headers() -> dict:
    """访问后端 API 时携带的服务凭据请求头"""
    return {"X-API-Key": TIANSHU_API_KEY} if TIANSHU_API_KEY else {}


def _error_response(message: str) -> list[TextContent]:
    """统一的错误响应：固定文案，不回显 URL、状态码、异常详情等内部信息"""
    return [TextContent(type="text", text=json.dumps({"error": message}, indent=2))]


def _validate_download_url(url: str) -> None:
    """下载目标校验（SSRF 防护）：仅允许 http/https，且解析出的所有 IP 必须为公网地址

    注意：校验通过后 aiohttp 建连时会再次进行 DNS 解析，仍存在 DNS 重绑定的
    残余风险，已通过"一次性解析校验 + allow_redirects=False"尽量收敛。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must contain a hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError("Failed to resolve hostname") from e
    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("URL resolves to a non-public address")


class MCPAuthMiddleware:
    """Pure ASGI 鉴权中间件：/sse 与 /messages 强制校验密钥，其余路径（/health、/）公开

    密钥来源：请求头 X-API-Key 或 Authorization: Bearer <key>，
    与环境变量 MCP_API_KEYS（逗号分隔）中的密钥做常量时间比较。
    MCP_API_KEYS 为空时任何密钥都无法通过，受保护端点一律 401。
    """

    PROTECTED_PATHS = ("/sse", "/messages")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "") not in self.PROTECTED_PATHS:
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        provided = headers.get("x-api-key", "")
        if not provided:
            authorization = headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                provided = authorization[len("bearer ") :].strip()

        if provided and any(hmac.compare_digest(provided, key) for key in MCP_API_KEYS):
            await self.app(scope, receive, send)
            return

        logger.warning(f"🔒 Unauthorized MCP access from {scope.get('client')}")
        await JSONResponse({"error": "Unauthorized"}, status_code=401)(scope, receive, send)


# 初始化 MCP Server
app = Server("mineru-tianshu")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用的工具"""
    return [
        Tool(
            name="parse_document",
            description="""
解析文档（PDF、图片、Office文档等）为 Markdown 格式。

📁 支持 2 种文件输入方式：
1. file_base64: Base64 编码的文件内容（推荐用于小文件）
2. file_url: 公网可访问的文件 URL（服务器会自动下载）

支持的文件格式：
- PDF 和图片（使用 MinerU GPU 加速解析）
- Office 文档（Word、Excel、PowerPoint）
- 网页和文本（HTML、Markdown、TXT、CSV）

功能特性：
- 公式识别和表格识别
- 支持中英文、日文、韩文等多语言
- 支持任务优先级设置
- 异步处理，可选择等待完成或稍后查询
            """.strip(),
            inputSchema={
                "type": "object",
                "properties": {
                    # 方式 1: Base64 编码（小文件推荐）
                    "file_base64": {
                        "type": "string",
                        "description": "Base64 编码的文件内容",
                    },
                    "file_name": {"type": "string", "description": "文件名（使用 file_base64 时必需）"},
                    # 方式 2: URL 下载
                    "file_url": {"type": "string", "description": "文件的公网 URL（服务器会自动下载）"},
                    # 解析选项
                    "backend": {
                        "type": "string",
                        "enum": [
                            "auto",
                            "pipeline",
                            "vlm-auto-engine",
                            "hybrid-auto-engine",
                            "vlm-http-client",
                            "hybrid-http-client",
                            "sensevoice",
                            "video",
                        ],
                        "description": "处理后端，默认: pipeline",
                        "default": "pipeline",
                    },
                    "lang": {
                        "type": "string",
                        "enum": ["ch", "en", "korean", "japan"],
                        "description": "文档语言，默认: ch",
                        "default": "ch",
                    },
                    "method": {
                        "type": "string",
                        "enum": ["auto", "txt", "ocr"],
                        "description": "解析方法，默认: auto",
                        "default": "auto",
                    },
                    "formula_enable": {
                        "type": "boolean",
                        "description": "是否启用公式识别，默认: true",
                        "default": True,
                    },
                    "table_enable": {"type": "boolean", "description": "是否启用表格识别，默认: true", "default": True},
                    "priority": {
                        "type": "integer",
                        "description": "任务优先级（0-100），数字越大越优先，默认: 0",
                        "default": 0,
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "wait_for_completion": {
                        "type": "boolean",
                        "description": "是否等待任务完成，默认: true",
                        "default": True,
                    },
                    "max_wait_seconds": {
                        "type": "integer",
                        "description": "最大等待时间（秒），默认: 300",
                        "default": 300,
                        "minimum": 10,
                        "maximum": 3600,
                    },
                },
                # 必须提供 2 种方式之一
                "oneOf": [{"required": ["file_base64", "file_name"]}, {"required": ["file_url"]}],
            },
        ),
        Tool(
            name="get_task_status",
            description="""
查询文档解析任务的状态和结果。

可以查询任务的：
- 当前状态（pending/processing/completed/failed/cancelled）
- 处理进度和时间信息
- 错误信息（如果失败）
- 解析结果内容（如果完成）
            """.strip(),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID（由 parse_document 返回）"},
                    "include_content": {
                        "type": "boolean",
                        "description": "是否包含完整的解析结果内容，默认: true",
                        "default": True,
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="list_tasks",
            description="""
列出最近的文档解析任务。

可以按状态筛选，查看任务队列情况。
            """.strip(),
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "processing", "completed", "failed", "cancelled"],
                        "description": "筛选指定状态的任务（可选，不填则返回所有状态）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制，默认: 10",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
            },
        ),
        Tool(
            name="get_queue_stats",
            description="""
获取任务队列统计信息。

返回各个状态的任务数量，了解系统负载情况。
            """.strip(),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """处理工具调用"""
    try:
        logger.info(f"🔧 Tool called: {name}")

        if name == "parse_document":
            return await parse_document(arguments)
        elif name == "get_task_status":
            return await get_task_status(arguments)
        elif name == "list_tasks":
            return await list_tasks(arguments)
        elif name == "get_queue_stats":
            return await get_queue_stats(arguments)
        else:
            return _error_response(f"Unknown tool: {name}")
    except Exception as e:
        logger.error(f"❌ Tool call failed: {name}, error: {e}")
        logger.exception(e)
        return _error_response("Tool execution failed")


async def parse_document(args: dict) -> list[TextContent]:
    """解析文档 - 支持 Base64 和 URL 两种输入方式"""
    async with aiohttp.ClientSession() as session:
        temp_file_path = None
        file_data = None
        file_name = None

        try:
            # 方式 1: Base64 编码
            if "file_base64" in args:
                logger.info("📦 Receiving file via Base64 encoding")

                try:
                    # Security: Safe use of base64 for file transmission via MCP protocol
                    # This is legitimate business logic, not code obfuscation
                    file_content = base64.b64decode(args["file_base64"])
                except Exception as e:
                    logger.warning(f"Invalid base64 payload: {e}")
                    return _error_response("Invalid base64 encoding")

                try:
                    file_name = sanitize_filename(args["file_name"])
                except FilenameValidationError:
                    logger.warning(f"🔒 Rejected unsafe file name: {args['file_name']!r}")
                    return _error_response("Invalid file name")

                # 检查文件大小（如果设置了限制）
                size_mb = len(file_content) / (1024 * 1024)
                if MAX_FILE_SIZE_BYTES > 0 and size_mb > MAX_FILE_SIZE_MB:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "error": f"File too large ({size_mb:.1f}MB). Maximum size is {MAX_FILE_SIZE_MB:.0f}MB."
                                },
                                indent=2,
                            ),
                        )
                    ]

                logger.info(f"📦 File: {file_name}, Size: {size_mb:.2f}MB")

                # 创建临时文件（使用共享上传目录，随机文件名 + 白名单扩展名）
                project_root = Path(__file__).parent.parent
                default_upload = project_root / "data" / "uploads"
                upload_dir = Path(os.getenv("UPLOAD_PATH", str(default_upload)))
                upload_dir.mkdir(parents=True, exist_ok=True)
                temp_file_path = ensure_within_directory(
                    upload_dir / f"{uuid.uuid4().hex}{Path(file_name).suffix}", upload_dir
                )
                temp_file_path.write_bytes(file_content)
                file_data = open(temp_file_path, "rb")

            # 方式 2: URL 下载
            elif "file_url" in args:
                url = args["file_url"]
                logger.info(f"🌐 Downloading file from URL: {url}")

                # SSRF 防护：先校验 scheme 与解析 IP，失败时仅返回固定文案
                try:
                    _validate_download_url(url)
                except ValueError as e:
                    logger.warning(f"🔒 Rejected download URL {url}: {e}")
                    return _error_response("Failed to download file")

                try:
                    # 禁止跟随重定向，防止重定向绕过目标校验
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=60), allow_redirects=False) as resp:
                        if resp.status != 200:
                            logger.warning(f"Download failed: HTTP {resp.status}")
                            return _error_response("Failed to download file")

                        # 从 URL 推断文件名
                        file_name = Path(urlparse(url).path).name or "downloaded_file"

                        # 尝试从 Content-Disposition 获取文件名（剔除引号/分隔符/路径穿越字符）
                        if "content-disposition" in resp.headers:
                            cd = resp.headers["content-disposition"]
                            match = re.search(r'filename[*]?=["\']?([^"\';\r\n/\\]+)', cd)
                            if match:
                                file_name = match.group(1).strip()

                        try:
                            file_name = sanitize_filename(file_name)
                        except FilenameValidationError:
                            logger.warning(f"🔒 Rejected downloaded file name: {file_name!r}")
                            return _error_response("Failed to download file")

                        # 流式读取并设上限，超限中止，防止超大响应打爆内存
                        buffer = bytearray()
                        async for chunk in resp.content.iter_chunked(1024 * 1024):
                            buffer.extend(chunk)
                            if len(buffer) > MAX_DOWNLOAD_SIZE_BYTES:
                                logger.warning("Download aborted: response exceeds 200MB limit")
                                return _error_response("Downloaded file too large")
                        file_content = bytes(buffer)
                        size_mb = len(file_content) / (1024 * 1024)

                        if MAX_FILE_SIZE_BYTES > 0 and size_mb > MAX_FILE_SIZE_MB:
                            return [
                                TextContent(
                                    type="text",
                                    text=json.dumps(
                                        {
                                            "error": f"Downloaded file too large ({size_mb:.1f}MB). Maximum size is {MAX_FILE_SIZE_MB:.0f}MB."
                                        },
                                        indent=2,
                                    ),
                                )
                            ]

                        logger.info(f"📦 Downloaded: {file_name}, Size: {size_mb:.2f}MB")

                        # 创建临时文件（使用共享上传目录，随机文件名 + 白名单扩展名）
                        project_root = Path(__file__).parent.parent
                        default_upload = project_root / "data" / "uploads"
                        upload_dir = Path(os.getenv("UPLOAD_PATH", str(default_upload)))
                        upload_dir.mkdir(parents=True, exist_ok=True)
                        temp_file_path = ensure_within_directory(
                            upload_dir / f"{uuid.uuid4().hex}{Path(file_name).suffix}", upload_dir
                        )
                        temp_file_path.write_bytes(file_content)
                        file_data = open(temp_file_path, "rb")

                except asyncio.TimeoutError:
                    logger.warning(f"Timeout downloading file from {url}")
                    return _error_response("Failed to download file")
                except Exception as e:
                    logger.warning(f"Failed to download file from {url}: {e}")
                    return _error_response("Failed to download file")

            else:
                return [
                    TextContent(
                        type="text", text=json.dumps({"error": "Must provide either file_base64 or file_url"}, indent=2)
                    )
                ]

            # 提交任务到 API Server
            form_data = aiohttp.FormData()
            form_data.add_field("file", file_data, filename=file_name)
            form_data.add_field("backend", args.get("backend", "pipeline"))
            form_data.add_field("lang", args.get("lang", "ch"))
            form_data.add_field("method", args.get("method", "auto"))
            form_data.add_field("formula_enable", str(args.get("formula_enable", True)).lower())
            form_data.add_field("table_enable", str(args.get("table_enable", True)).lower())
            form_data.add_field("priority", str(args.get("priority", 0)))

            logger.info(f"📤 Submitting task for: {file_name}")

            async with session.post(
                f"{API_BASE_URL}/api/v1/tasks/submit", data=form_data, headers=_api_headers()
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {"error": "Failed to submit task", "details": error_text, "status_code": resp.status},
                                indent=2,
                            ),
                        )
                    ]

                result = await resp.json()
                task_id = result["task_id"]
                logger.info(f"✅ Task submitted: {task_id}")

            # 是否等待完成
            if not args.get("wait_for_completion", True):
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "status": "submitted",
                                "task_id": task_id,
                                "file_name": file_name,
                                "message": "Task submitted successfully. Use get_task_status to check progress.",
                            },
                            indent=2,
                            ensure_ascii=False,
                        ),
                    )
                ]

            # 等待任务完成
            logger.info(f"⏳ Waiting for task completion: {task_id}")
            max_wait = args.get("max_wait_seconds", 300)
            poll_interval = 2
            elapsed = 0

            while elapsed < max_wait:
                async with session.get(f"{API_BASE_URL}/api/v1/tasks/{task_id}", headers=_api_headers()) as resp:
                    if resp.status != 200:
                        return [
                            TextContent(
                                type="text",
                                text=json.dumps({"error": "Failed to query task status", "task_id": task_id}, indent=2),
                            )
                        ]

                    task_status = await resp.json()
                    status = task_status["status"]

                    if status == "completed":
                        # 任务完成，返回结果
                        logger.info(f"✅ Task completed: {task_id}")
                        content = task_status.get("data", {}).get("content", "") if task_status.get("data") else ""

                        return [
                            TextContent(
                                type="text",
                                text=json.dumps(
                                    {
                                        "status": "completed",
                                        "task_id": task_id,
                                        "file_name": file_name,
                                        "content": content,
                                        "processing_time": _calculate_processing_time(task_status),
                                        "created_at": task_status.get("created_at"),
                                        "started_at": task_status.get("started_at"),
                                        "completed_at": task_status.get("completed_at"),
                                    },
                                    indent=2,
                                    ensure_ascii=False,
                                ),
                            )
                        ]

                    elif status == "failed":
                        logger.error(f"❌ Task failed: {task_id}")
                        return [
                            TextContent(
                                type="text",
                                text=json.dumps(
                                    {
                                        "status": "failed",
                                        "task_id": task_id,
                                        "file_name": file_name,
                                        "error": task_status.get("error_message", "Unknown error"),
                                        "created_at": task_status.get("created_at"),
                                        "started_at": task_status.get("started_at"),
                                        "completed_at": task_status.get("completed_at"),
                                    },
                                    indent=2,
                                    ensure_ascii=False,
                                ),
                            )
                        ]

                    elif status == "cancelled":
                        logger.warning(f"⚠️ Task cancelled: {task_id}")
                        return [
                            TextContent(
                                type="text",
                                text=json.dumps(
                                    {"status": "cancelled", "task_id": task_id, "file_name": file_name},
                                    indent=2,
                                    ensure_ascii=False,
                                ),
                            )
                        ]

                    elif status in ["pending", "processing"]:
                        await asyncio.sleep(poll_interval)
                        elapsed += poll_interval
                        if elapsed % 10 == 0:  # 每 10 秒记录一次
                            logger.info(f"⏳ Task {task_id} status: {status}, elapsed: {elapsed}s")

                    else:
                        return [
                            TextContent(
                                type="text",
                                text=json.dumps(
                                    {"status": status, "task_id": task_id, "file_name": file_name},
                                    indent=2,
                                    ensure_ascii=False,
                                ),
                            )
                        ]

            # 超时
            logger.warning(f"⏰ Task timeout: {task_id}")
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "timeout",
                            "task_id": task_id,
                            "file_name": file_name,
                            "message": f"Task did not complete within {max_wait} seconds. Use get_task_status to check later.",
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                )
            ]

        finally:
            # 清理文件和临时文件
            if file_data is not None:
                try:
                    if not file_data.closed:
                        file_data.close()
                        logger.debug(f"Closed file handle for: {file_name}")
                except Exception as e:
                    logger.warning(f"Failed to close file handle: {e}")
            if temp_file_path is not None:
                try:
                    if temp_file_path.exists():
                        temp_file_path.unlink()
                        logger.info(f"Cleaned temp file: {temp_file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete temp file: {e}")


async def get_task_status(args: dict) -> list[TextContent]:
    """查询任务状态"""
    task_id = args["task_id"]
    include_content = args.get("include_content", True)

    logger.info(f"📊 Querying task status: {task_id}")

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/api/v1/tasks/{task_id}", headers=_api_headers()) as resp:
            if resp.status == 404:
                return [TextContent(type="text", text=json.dumps({"error": f"Task not found: {task_id}"}, indent=2))]

            if resp.status != 200:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": "Failed to query task status", "task_id": task_id}, indent=2),
                    )
                ]

            task = await resp.json()

            # 构建响应
            response = {
                "task_id": task_id,
                "status": task["status"],
                "file_name": task["file_name"],
                "backend": task["backend"],
                "priority": task["priority"],
                "created_at": task["created_at"],
                "started_at": task["started_at"],
                "completed_at": task["completed_at"],
                "worker_id": task["worker_id"],
                "retry_count": task["retry_count"],
            }

            if task.get("error_message"):
                response["error_message"] = task["error_message"]

            if include_content and task["status"] == "completed" and task.get("data"):
                response["content"] = task["data"].get("content", "")
                response["processing_time"] = _calculate_processing_time(task)
                if task["data"].get("markdown_file"):
                    response["markdown_file"] = task["data"]["markdown_file"]

            return [TextContent(type="text", text=json.dumps(response, indent=2, ensure_ascii=False))]


async def list_tasks(args: dict) -> list[TextContent]:
    """列出任务"""
    status = args.get("status")
    limit = args.get("limit", 10)

    logger.info(f"📋 Listing tasks: status={status}, limit={limit}")

    params = {"limit": limit}
    if status:
        params["status"] = status

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/api/v1/queue/tasks", params=params, headers=_api_headers()) as resp:
            if resp.status != 200:
                return [TextContent(type="text", text=json.dumps({"error": "Failed to list tasks"}, indent=2))]

            result = await resp.json()
            tasks = result["tasks"]

            # 简化任务信息
            simplified_tasks = [
                {
                    "task_id": t["task_id"],
                    "file_name": t["file_name"],
                    "status": t["status"],
                    "backend": t["backend"],
                    "priority": t["priority"],
                    "created_at": t["created_at"],
                    "started_at": t["started_at"],
                    "completed_at": t["completed_at"],
                    "worker_id": t["worker_id"],
                }
                for t in tasks
            ]

            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"count": len(simplified_tasks), "tasks": simplified_tasks}, indent=2, ensure_ascii=False
                    ),
                )
            ]


async def get_queue_stats(args: dict) -> list[TextContent]:
    """获取队列统计"""
    logger.info("📊 Getting queue stats")

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/api/v1/queue/stats", headers=_api_headers()) as resp:
            if resp.status != 200:
                return [TextContent(type="text", text=json.dumps({"error": "Failed to get queue stats"}, indent=2))]

            result = await resp.json()

            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "stats": result["stats"],
                            "total": result.get("total", sum(result["stats"].values())),
                            "timestamp": result.get("timestamp"),
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                )
            ]


def _calculate_processing_time(task: dict) -> str:
    """计算处理时间"""
    from datetime import datetime

    if task.get("started_at") and task.get("completed_at"):
        try:
            start = datetime.fromisoformat(task["started_at"])
            end = datetime.fromisoformat(task["completed_at"])
            duration = (end - start).total_seconds()
            return f"{duration:.2f} seconds"
        except Exception:
            return "N/A"
    return "N/A"


async def main():
    """启动 MCP Server (SSE 模式)"""
    logger.info("=" * 60)
    logger.info("🚀 Starting MinerU Tianshu MCP Server")
    logger.info("=" * 60)
    logger.info(f"📡 API Base URL: {API_BASE_URL}")

    # 从环境变量读取配置（默认仅监听回环地址，避免未认证暴露到公网）
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8002"))

    if not MCP_API_KEYS:
        logger.warning("⚠️ MCP_API_KEYS 未配置：/sse 与 /messages 将对所有请求返回 401")

    # 创建 SSE Transport，启用 DNS 重绑定 / Host / Origin 防护
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{host}:*", "localhost:*", "127.0.0.1:*", "[::1]:*"],
        allowed_origins=[
            f"http://{host}:*",
            f"https://{host}:*",
            "http://localhost:*",
            "https://localhost:*",
            "http://127.0.0.1:*",
            "https://127.0.0.1:*",
            "http://[::1]:*",
            "https://[::1]:*",
        ],
    )
    sse = SseServerTransport("/messages", security_settings=security_settings)

    # SSE 处理函数
    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    # POST 消息处理函数
    async def handle_messages(request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    # 健康检查端点（公开，不返回版本号、工具列表、端点结构等可被用于信息收集的内容）
    async def health_check(request):
        return JSONResponse({"status": "healthy"})

    # 创建 Starlette 应用，受保护端点外挂鉴权中间件
    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
            Route("/health", endpoint=health_check, methods=["GET"]),
            Route("/", endpoint=health_check, methods=["GET"]),  # 根路径也返回健康检查
        ]
    )
    starlette_app = MCPAuthMiddleware(starlette_app)

    logger.info(f"🌐 MCP Server listening on http://{host}:{port}")
    logger.info(f"📡 SSE endpoint: http://{host}:{port}/sse")
    logger.info(f"📮 Messages endpoint: http://{host}:{port}/messages")
    logger.info(f"🏥 Health check: http://{host}:{port}/health")
    logger.info("📚 Available tools: parse_document, get_task_status, list_tasks, get_queue_stats")
    logger.info("=" * 60)

    config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 MCP Server stopped by user")
    except Exception as e:
        logger.error(f"❌ MCP Server failed to start: {e}")
        logger.exception(e)
        sys.exit(1)
