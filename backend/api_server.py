"""
MinerU Tianshu - API Server
天枢 API 服务器

企业级 AI 数据预处理平台
支持文档、图片、音频、视频等多模态数据处理
提供 RESTful API 接口用于任务提交、查询和管理
企业级认证授权: JWT Token + API Key + SSO
"""

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Query, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from loguru import logger
from starlette.types import ASGIApp, Receive, Scope, Send  # ✅ 用于底层中间件

# 导入认证模块
from auth import (
    User,
    Permission,
    get_current_active_user,
    require_permission,
)
from auth.auth_db import AuthDB
from auth.dependencies import get_current_user_flexible
from auth.routes import router as auth_router
from task_db import TaskDB
from utils import FilenameValidationError, ensure_within_directory, sanitize_filename

# 初始化 FastAPI 应用
app = FastAPI(
    title="MinerU Tianshu API",
    description="天枢 - 企业级 AI 数据预处理平台 | 支持文档、图片、音频、视频等多模态数据处理 | 企业级认证授权",
    version="2.0.0",
    # 不设置 servers，让 FastAPI 自动根据请求的 Host 生成
)


# ============================================================================
# ✅ 终极修复：ASGI 路径重写中间件
# 彻底解决 Nginx proxy_pass 剥离 /api/ 导致所有后端接口(特别是 auth)报 404 的问题
# ============================================================================
class NginxPathRewriteMiddleware:
    """拦截底层 ASGI 请求，给被 Nginx 剥离的路径补全前缀"""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            # 如果收到 Nginx 发来的 /v1/...，自动补全为 /api/v1/...
            if path.startswith("/v1/"):
                scope["path"] = f"/api{path}"
                # 某些底层组件匹配强依赖 raw_path，也一并修改
                if "raw_path" in scope:
                    scope["raw_path"] = b"/api" + scope["raw_path"]
        await self.app(scope, receive, send)


# 必须最先添加此中间件！
app.add_middleware(NginxPathRewriteMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """兜底异常处理：对外隐藏内部细节，完整堆栈仅记录日志"""
    logger.exception(f"❌ Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _parse_allowed_origins() -> list:
    """解析允许跨域的来源列表；未配置或含通配符时回退本地开发默认值（避免裸奔）"""
    default_origins = ["http://localhost:3000", "http://localhost:5173"]
    raw = os.getenv("ALLOWED_ORIGINS", ",".join(default_origins))
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if not origins or "*" in origins:
        logger.warning("⚠️  ALLOWED_ORIGINS 未配置或包含通配符 '*'，CORS 回退到本地开发默认来源")
        return default_origins
    return origins


# 添加 CORS 中间件（不允许携带凭据，来源白名单化）
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# 获取项目根目录（backend 的父目录）
PROJECT_ROOT = Path(__file__).parent.parent

# 初始化数据库
# 确保使用环境变量中的数据库路径（与 Worker 保持一致）
db_path_env = os.getenv("DATABASE_PATH")
if db_path_env:
    db_path = str(Path(db_path_env).resolve())
    logger.info(f"📊 API Server using DATABASE_PATH: {db_path_env} -> {db_path}")
    db = TaskDB(db_path)
else:
    logger.warning("⚠️  DATABASE_PATH not set in API Server, using default")
    # Docker 环境: /app/data/db/mineru_tianshu.db
    # 本地环境: ./data/db/mineru_tianshu.db
    default_db_path = PROJECT_ROOT / "data" / "db" / "mineru_tianshu.db"
    default_db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path = str(default_db_path.resolve())
    logger.info(f"📊 Using default database path: {db_path}")
    db = TaskDB(db_path)
auth_db = AuthDB()

# 注册认证路由
app.include_router(auth_router)

# ==============================================================================
# 目录配置 (Output & Upload)
# ==============================================================================

# 1. 配置输出目录（使用共享目录，Docker 环境可访问）
output_path_env = os.getenv("OUTPUT_PATH")
if output_path_env:
    OUTPUT_DIR = Path(output_path_env).resolve()
else:
    # Docker 环境: /app/output
    # 本地环境: ./data/output
    OUTPUT_DIR = (PROJECT_ROOT / "data" / "output").resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
logger.info(f"📁 Output directory: {OUTPUT_DIR}")

# 2. 配置上传目录 (修改默认为 input)
upload_path_env = os.getenv("UPLOAD_PATH")
if upload_path_env:
    UPLOAD_DIR = Path(upload_path_env).resolve()
else:
    # Docker 环境: /app/input (如果不设置环境变量)
    # 本地环境: ./input (项目根目录下的 input 目录)
    UPLOAD_DIR = (PROJECT_ROOT / "input").resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
logger.info(f"📁 Upload directory: {UPLOAD_DIR}")

# 文件响应 MIME 白名单：仅 PDF 与常见图片允许内联预览，其余一律强制下载，
# 防止用户上传的 HTML/SVG 等被浏览器内联解析造成存储型 XSS
INLINE_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _build_file_response(full_path: Path) -> FileResponse:
    """构造安全的文件下载/预览响应（MIME 白名单 + 安全响应头）"""
    media_type = INLINE_MIME_TYPES.get(full_path.suffix.lower())
    disposition = "inline" if media_type else "attachment"
    headers = {
        "Content-Disposition": f"{disposition}; filename*=utf-8''{quote(full_path.name)}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    return FileResponse(path=str(full_path), media_type=media_type or "application/octet-stream", headers=headers)


# 注意：此函数已废弃，Worker 已自动上传图片到 RustFS 并替换 URL
def process_markdown_images_legacy(md_content: str, image_dir: Path, result_path: str):
    """
    【向后兼容】处理 Markdown 中的图片引用
    """
    if "http://" in md_content or "https://" in md_content:
        return md_content

    if not image_dir.exists():
        return md_content

    def replace_image_path(match):
        full_match = match.group(0)
        if "![" in full_match:
            image_path = match.group(2)
            alt_text = match.group(1)
        else:
            image_path = match.group(2)
            alt_text = "Image"

        if image_path.startswith("http"):
            return full_match

        try:
            image_filename = Path(image_path).name
            output_dir_str = str(OUTPUT_DIR).replace("\\", "/")
            result_path_str = result_path.replace("\\", "/")

            if result_path_str.startswith(output_dir_str):
                relative_path = result_path_str[len(output_dir_str) :].lstrip("/")
                encoded_relative_path = quote(relative_path, safe="/")
                encoded_filename = quote(image_filename, safe="/")

                static_url = f"/api/v1/files/output/{encoded_relative_path}/images/{encoded_filename}"

                if "![" in full_match:
                    return f"![{alt_text}]({static_url})"
                else:
                    return full_match.replace(image_path, static_url)
        except Exception as e:
            logger.error(f"❌ Failed to generate local URL: {e}")

        return full_match

    try:
        md_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
        html_pattern = r'<img\s+([^>]*\s+)?src="([^"]+)"([^>]*)>'

        new_content = re.sub(md_pattern, replace_image_path, md_content)
        new_content = re.sub(html_pattern, replace_image_path, new_content)
        return new_content
    except Exception:
        return md_content


@app.get("/", tags=["系统信息"])
async def root():
    """API根路径"""
    return {
        "service": "MinerU Tianshu",
        "version": "2.0.0",
        "description": "天枢 - 企业级 AI 数据预处理平台",
        "features": "文档、图片、音频、视频等多模态数据处理",
        "docs": "/docs",
    }


# ============================================================================
# 创建 API Router
# ============================================================================
router = APIRouter()


@router.post("/tasks/submit", tags=["任务管理"])
async def submit_task(
    file: UploadFile = File(..., description="文件: PDF/图片/Office/HTML/音频/视频等多种格式"),
    backend: str = Form(
        "auto",
        description="处理后端: pipeline, hybrid-auto-engine, vlm-auto-engine, hybrid-http-client, vlm-http-client, sensevoice, video, etc.",
    ),
    lang: str = Form("auto", description="语言: ch/en/auto..."),
    method: str = Form("auto", description="解析方法: auto/txt/ocr"),
    formula_enable: bool = Form(True, description="是否启用公式识别"),
    table_enable: bool = Form(True, description="是否启用表格识别"),
    priority: int = Form(0, description="优先级，数字越大越优先"),
    start_page: Optional[int] = Form(None, description="起始页码（从0开始）"),
    end_page: Optional[int] = Form(None, description="结束页码"),
    force_ocr: bool = Form(False, description="[兼容旧版] 是否强制使用OCR"),
    server_url: Optional[str] = Form(None, description="远程服务器地址 (仅 Client 模式需要)"),
    draw_layout_bbox: bool = Form(True, description="绘制布局边框 (_layout.pdf)"),
    draw_span_bbox: bool = Form(True, description="绘制文本边框 (_span.pdf)"),
    dump_markdown: bool = Form(True, description="输出 Markdown"),
    dump_middle_json: bool = Form(True, description="输出中间 JSON"),
    dump_model_output: bool = Form(True, description="输出模型原始数据"),
    dump_content_list: bool = Form(True, description="输出内容列表"),
    dump_orig_pdf: bool = Form(True, description="保存原始/截取 PDF"),
    draw_layout: bool = Form(True, description="[兼容旧版] 是否绘制布局边框"),
    draw_span: bool = Form(True, description="[兼容旧版] 是否绘制文本Span边框"),
    keep_audio: bool = Form(False, description="视频处理时是否保留提取的音频文件"),
    enable_keyframe_ocr: bool = Form(False, description="是否启用视频关键帧OCR识别（实验性功能）"),
    ocr_backend: str = Form("mineru", description="关键帧OCR引擎: mineru"),
    keep_keyframes: bool = Form(False, description="是否保留提取的关键帧图像"),
    enable_speaker_diarization: bool = Form(False, description="是否启用说话人分离"),
    remove_watermark: bool = Form(False, description="是否启用水印去除"),
    watermark_conf_threshold: float = Form(0.35, description="水印检测置信度阈值"),
    watermark_dilation: int = Form(10, description="水印掩码膨胀大小"),
    current_user: User = Depends(require_permission(Permission.TASK_SUBMIT)),
):
    # 校验并净化文件名（路径穿越或不支持的类型直接 400）
    try:
        safe_name = sanitize_filename(file.filename or "")
    except FilenameValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid file name: {e}")

    try:
        # 落盘文件名完全由服务端生成（UUID + 白名单扩展名），不使用任何用户输入
        unique_filename = f"{uuid.uuid4().hex}{Path(safe_name).suffix}"
        temp_file_path = ensure_within_directory(UPLOAD_DIR / unique_filename, UPLOAD_DIR)

        with open(temp_file_path, "wb") as temp_file:
            while True:
                chunk = await file.read(1 << 23)
                if not chunk:
                    break
                temp_file.write(chunk)

        options = {
            "lang": lang,
            "method": method,
            "formula_enable": formula_enable,
            "table_enable": table_enable,
            "start_page": start_page,
            "end_page": end_page,
            "force_ocr": force_ocr,
            "server_url": server_url,
            "draw_layout_bbox": draw_layout_bbox,
            "draw_span_bbox": draw_span_bbox,
            "dump_markdown": dump_markdown,
            "dump_middle_json": dump_middle_json,
            "dump_model_output": dump_model_output,
            "dump_content_list": dump_content_list,
            "dump_orig_pdf": dump_orig_pdf,
            "draw_layout": draw_layout,
            "draw_span": draw_span,
            "keep_audio": keep_audio,
            "enable_keyframe_ocr": enable_keyframe_ocr,
            "ocr_backend": ocr_backend,
            "keep_keyframes": keep_keyframes,
            "enable_speaker_diarization": enable_speaker_diarization,
            "remove_watermark": remove_watermark,
            "watermark_conf_threshold": watermark_conf_threshold,
            "watermark_dilation": watermark_dilation,
        }

        options["upload_images"] = os.getenv("RUSTFS_ENABLED", "true").lower() == "true"

        task_id = db.create_task(
            file_name=file.filename,
            file_path=str(temp_file_path),
            backend=backend,
            options=options,
            priority=priority,
            user_id=current_user.user_id,
        )

        logger.info(f"✅ Task submitted: {task_id} - {file.filename}")
        return {
            "success": True,
            "task_id": task_id,
            "status": "pending",
            "message": "Task submitted successfully",
            "file_name": file.filename,
            "user_id": current_user.user_id,
            "created_at": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to submit task: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit task")


@router.get("/tasks/{task_id}", tags=["任务管理"])
async def get_task_status(
    task_id: str,
    upload_images: bool = Query(False, description="【已废弃】图片已自动上传到 RustFS"),
    format: str = Query("markdown", description="返回格式: markdown(默认)/json/both"),
    current_user: User = Depends(get_current_active_user),
):
    task = db.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not current_user.has_permission(Permission.TASK_VIEW_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied: You can only view your own tasks")

    source_url = None
    if task.get("file_path"):
        try:
            source_filename = Path(task["file_path"]).name
            encoded_source_filename = quote(source_filename)
            source_url = f"/api/v1/files/upload/{encoded_source_filename}"
        except Exception as e:
            logger.warning(f"Failed to generate source_url: {e}")

    response = {
        "success": True,
        "task_id": task_id,
        "status": task["status"],
        "file_name": task["file_name"],
        "source_url": source_url,
        "backend": task["backend"],
        "priority": task["priority"],
        "error_message": task["error_message"],
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "completed_at": task["completed_at"],
        "user_id": task.get("user_id"),
    }

    if not task.get("is_parent"):
        response["worker_id"] = task.get("worker_id")
        response["retry_count"] = task.get("retry_count")
        response["result_path"] = task.get("result_path")

    if task.get("is_parent"):
        child_count = task.get("child_count", 0)
        child_completed = task.get("child_completed", 0)
        response["is_parent"] = True
        response["subtask_progress"] = {
            "total": child_count,
            "completed": child_completed,
            "percentage": round(child_completed / child_count * 100, 1) if child_count > 0 else 0,
        }
        try:
            children = db.get_child_tasks(task_id)
            response["subtasks"] = [
                {
                    "task_id": child["task_id"],
                    "status": child["status"],
                    "chunk_info": json.loads(child.get("options", "{}")).get("chunk_info"),
                    "error_message": child.get("error_message"),
                }
                for child in children
            ]
        except Exception:
            pass

    if task["status"] == "completed":
        if not task["result_path"] or task["result_path"] == "CLEARED":
            response["data"] = None
            response["message"] = "Task completed but result files have been cleaned up"
            return response

        result_dir = Path(task["result_path"])
        if result_dir.exists():
            md_files = list(result_dir.rglob("*.md"))
            json_files = [
                f
                for f in result_dir.rglob("*.json")
                if f.name in ["content.json", "result.json"] or "_content_list.json" in f.name
            ]

            if md_files or json_files:
                try:
                    response["data"] = {}
                    response["data"]["json_available"] = len(json_files) > 0

                    pdf_files = list(result_dir.rglob("*.pdf"))
                    preview_pdf = None
                    for pdf in pdf_files:
                        if "_layout.pdf" in pdf.name:
                            preview_pdf = pdf
                            break
                    if not preview_pdf:
                        for pdf in pdf_files:
                            if "_span.pdf" in pdf.name:
                                preview_pdf = pdf
                                break
                    if not preview_pdf and pdf_files:
                        preview_pdf = pdf_files[0]

                    if preview_pdf:
                        try:
                            rel_path = preview_pdf.relative_to(OUTPUT_DIR)
                            encoded_path = quote(str(rel_path).replace("\\", "/"), safe="/")
                            response["data"]["pdf_path"] = encoded_path
                        except ValueError:
                            pass

                    if format in ["markdown", "both"] and md_files:
                        md_file = next((f for f in md_files if f.name == "result.md"), md_files[0])
                        image_dir = md_file.parent / "images"
                        with open(md_file, "r", encoding="utf-8") as f:
                            md_content = f.read()

                        if image_dir.exists() and ("http://" not in md_content and "https://" not in md_content):
                            md_content = process_markdown_images_legacy(md_content, image_dir, task["result_path"])

                        response["data"]["markdown_file"] = md_file.name
                        response["data"]["content"] = md_content
                        response["data"]["has_images"] = image_dir.exists()

                    if format in ["json", "both"] and json_files:
                        import json as json_lib

                        json_file = json_files[0]
                        try:
                            with open(json_file, "r", encoding="utf-8") as f:
                                json_content = json_lib.load(f)
                            response["data"]["json_file"] = json_file.name
                            response["data"]["json_content"] = json_content
                        except Exception:
                            pass
                    elif format == "json" and not json_files:
                        response["data"]["message"] = "JSON format not available for this backend"

                    if not response["data"]:
                        response["data"] = None

                except Exception as e:
                    logger.error(f"❌ Failed to read content: {e}")
                    response["data"] = None
        else:
            logger.error(f"❌ Result directory does not exist: {result_dir}")

    return response


# ========================================================================
# 🚨 终极修复：物理清理任务接口（解决清理失败、任务依然存在问题）
# ========================================================================


@router.delete("/tasks/{task_id}", tags=["任务管理"])
async def delete_task(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    【重构】彻底删除任务及其本地文件
    不仅取消 pending 的任务，还会物理抹除文件和数据库记录。
    """
    task = db.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 权限检查
    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied: You can only delete your own tasks")

    # 1. 物理删除源文件与解析产物（带目录逃逸防护）
    db.delete_task_files(task)

    # 2. 从数据库彻底移除记录
    with db.get_cursor() as cursor:
        cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))

    logger.info(f"🗑️ Task completely deleted: {task_id} by user {current_user.username}")
    return {"success": True, "message": "Task and files completely deleted."}


@router.delete("/tasks/failed/clear", tags=["任务管理"])
async def clear_failed_tasks_endpoint(current_user: User = Depends(require_permission(Permission.TASK_DELETE_ALL))):
    """
    【重构】一键清理所有失败的任务，包含物理清除文件
    """
    deleted_count = db.clear_failed_tasks()

    logger.info(f"🧹 Cleared {deleted_count} failed tasks from DB and Disk by {current_user.username}.")
    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": f"Successfully cleared {deleted_count} failed tasks.",
    }


# ========================================================================
# 修复：重试与暂停权限报错 (TASK_MANAGE_ALL -> TASK_DELETE_ALL)
# ========================================================================


@router.post("/tasks/{task_id}/retry", tags=["任务管理"])
async def retry_task(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    重试失败的任务
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied")

    if db.retry_task(task_id):
        # 仅清理旧的解析产物，保留上传源文件供重试使用
        db.delete_task_files(task, include_source=False)

        return {"success": True, "message": "Task submitted for retry"}

    raise HTTPException(status_code=404, detail="Task not found")


@router.post("/tasks/{task_id}/cancel", tags=["任务管理"])
async def cancel_task_endpoint(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    取消任务：仅对 pending / processing / paused 状态的任务生效
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied")

    if db.cancel_task(task_id):
        return {"success": True, "message": "Task cancelled"}

    raise HTTPException(
        status_code=409, detail="Task cannot be cancelled (must be in pending/processing/paused status)"
    )


@router.post("/tasks/{task_id}/pause", tags=["任务管理"])
async def pause_task_endpoint(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    暂停任务
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied")

    if db.pause_task(task_id):
        return {"success": True, "message": "Task paused"}

    raise HTTPException(status_code=409, detail="Task cannot be paused (must be in pending status)")


@router.post("/tasks/{task_id}/resume", tags=["任务管理"])
async def resume_task_endpoint(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    恢复任务
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied")

    if db.resume_task(task_id):
        return {"success": True, "message": "Task resumed"}

    raise HTTPException(status_code=409, detail="Task cannot be resumed (must be in paused status)")


@router.post("/tasks/{task_id}/clear-cache", tags=["任务管理"])
async def clear_task_cache_endpoint(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    清理任务缓存：删除解析产物并标记 result_path 为已清理
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied")

    try:
        if db.clear_task_cache(task_id):
            return {"success": True, "message": "Task cache cleared, space freed"}
    except Exception as e:
        logger.error(f"❌ Failed to clear cache for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear cache")

    raise HTTPException(status_code=404, detail="Task not found")


@router.get("/queue/stats", tags=["队列管理"])
async def get_queue_stats(current_user: User = Depends(require_permission(Permission.QUEUE_VIEW))):
    stats = db.get_queue_stats()
    return {
        "success": True,
        "stats": stats,
        "total": sum(stats.values()),
        "timestamp": datetime.now().isoformat(),
        "user": current_user.username,
    }


@router.get("/queue/tasks", tags=["队列管理"])
async def list_tasks(
    status: Optional[str] = Query(None, description="筛选状态"),
    limit: int = Query(100, description="返回数量限制", le=1000),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    backend: Optional[str] = Query(None, description="筛选后端引擎"),
    search: Optional[str] = Query(None, description="搜索文件名或任务ID"),
    current_user: User = Depends(get_current_active_user),
):
    can_view_all = current_user.has_permission(Permission.TASK_VIEW_ALL)
    conditions = []
    params = []

    if not can_view_all:
        conditions.append("user_id = ?")
        params.append(current_user.user_id)

    if status:
        conditions.append("status = ?")
        params.append(status)
    if backend:
        conditions.append("backend = ?")
        params.append(backend)

    if search:
        search = search.strip()
        conditions.append("(file_name LIKE ? OR task_id = ?)")
        params.append(f"%{search}%")
        params.append(search)

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * page_size

    with db.get_cursor() as cursor:
        count_sql = f"SELECT COUNT(*) FROM tasks{where_clause}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        query_params = params + [page_size, offset]
        data_sql = f"""
            SELECT * FROM tasks
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(data_sql, query_params)
        tasks = [dict(row) for row in cursor.fetchall()]

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "count": len(tasks),
        "tasks": tasks,
        "can_view_all": can_view_all,
    }


@router.post("/admin/cleanup", tags=["系统管理"])
async def cleanup_old_tasks(
    days: int = Query(7, description="清理N天前的任务"),
    current_user: User = Depends(require_permission(Permission.QUEUE_MANAGE)),
):
    deleted_count = db.cleanup_old_task_records(days)
    logger.info(f"🧹 Cleaned up {deleted_count} old tasks by {current_user.username}")
    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": f"Cleaned up {deleted_count} tasks older than {days} days",
    }


@router.post("/admin/reset-stale", tags=["系统管理"])
async def reset_stale_tasks(
    timeout_minutes: int = Query(60, description="超时时间（分钟）"),
    current_user: User = Depends(require_permission(Permission.QUEUE_MANAGE)),
):
    reset_count = db.reset_stale_tasks(timeout_minutes)
    logger.info(f"🔄 Reset {reset_count} stale tasks by {current_user.username}")
    return {
        "success": True,
        "reset_count": reset_count,
        "message": f"Reset tasks processing for more than {timeout_minutes} minutes",
    }


@router.get("/engines", tags=["系统信息"])
async def list_engines(current_user: User = Depends(get_current_active_user)):
    """需要认证。返回系统中所有可用的处理引擎信息。"""
    import importlib.util
    import importlib.metadata
    import sys

    def _pkg_version(pkg: str) -> str:
        try:
            return importlib.metadata.version(pkg)
        except Exception:
            return "N/A"

    # ── 运行环境信息（仅保留平台标识，不暴露 Python/CUDA/GPU/依赖版本等内部细节）──
    system_info = {
        "platform": sys.platform,
    }

    # ── 引擎列表 ──────────────────────────────────────────────
    mineru_ver = _pkg_version("mineru")

    engines = {
        "document": [
            {
                "name": "pipeline",
                "display_name": "Standard Pipeline",
                "version": mineru_ver,
                "description": "基于 PDF-Extract-Kit 的传统多模型管道，速度快，无幻觉，适合大多数文档。",
                "supported_formats": [".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".pptx"],
            },
            {
                "name": "vlm-auto-engine",
                "display_name": "MinerU VLM (视觉大模型)",
                "version": mineru_ver,
                "description": "基于 MinerU 3.X (1.2B) 视觉模型，擅长处理复杂排版、图表和非标准文档。Office 文件将使用原生解析。",
                "supported_formats": [".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".pptx"],
            },
            {
                "name": "hybrid-auto-engine",
                "display_name": "Hybrid High-Precision (高精度混合)",
                "version": mineru_ver,
                "description": "结合 Pipeline 的稳定性与 VLM 的理解能力，提供最高精度的解析效果。Office 文件将使用原生解析。",
                "supported_formats": [".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".pptx"],
            },
        ],
        "ocr": [],
        "audio": [],
        "video": [],
        "format": [],
        "office": [
            {
                "name": "MarkItDown (快速)",
                "value": "auto",
                "version": _pkg_version("markitdown"),
                "description": "轻量文本和 HTML/CSV 文件转换引擎",
                "supported_formats": [".html", ".txt", ".csv"],
            },
            {
                "name": "LibreOffice 转换器（旧版 Office）",
                "value": "auto",
                "version": mineru_ver,
                "description": "将旧版 .doc/.xls/.ppt 转换为新版格式后由 MinerU 原生解析",
                "supported_formats": [".doc", ".xls", ".ppt"],
            },
        ],
    }

    if importlib.util.find_spec("audio_engines") is not None:
        engines["audio"].append(
            {
                "name": "sensevoice",
                "display_name": "SenseVoice",
                "version": _pkg_version("funasr"),
                "supported_formats": [".wav", ".mp3", ".flac", ".m4a", ".ogg"],
            }
        )

    if importlib.util.find_spec("video_engines") is not None:
        engines["video"].append(
            {
                "name": "video",
                "display_name": "Video Processing",
                "version": "N/A",
                "supported_formats": [".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv"],
            }
        )

    try:
        from format_engines import FormatEngineRegistry

        for engine_info in FormatEngineRegistry.list_engines():
            engines["format"].append(
                {
                    "name": engine_info["name"],
                    "display_name": engine_info["name"].upper(),
                    "version": engine_info.get("version", "N/A"),
                    "description": engine_info["description"],
                    "supported_formats": engine_info["extensions"],
                }
            )
    except ImportError:
        pass

    return {
        "success": True,
        "engines": engines,
        "system_info": system_info,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/health", tags=["系统信息"])
async def health_check():
    try:
        stats = db.get_queue_stats()
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": "connected",
            "queue_stats": stats,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(status_code=503, content={"status": "unhealthy"})


@router.get("/files/output/{file_path:path}", tags=["文件服务"])
async def serve_output_file(file_path: str, current_user: User = Depends(get_current_user_flexible)):
    """提供输出文件的访问服务（需认证，仅任务所有者或全局查看权限可访问）"""
    try:
        decoded_path = unquote(file_path).lstrip("/")
        full_path = (OUTPUT_DIR / decoded_path).resolve()

        if not full_path.is_relative_to(OUTPUT_DIR.resolve()) or not full_path.is_file():
            logger.warning(f"❌ Access denied or file not found: {full_path}")
            raise HTTPException(status_code=404, detail="File not found or access denied")

        # 归属校验：孤儿文件（任务已被删除的残留产物）仅全局查看权限可访问
        task = db.get_task_by_output_path(decoded_path)
        if task is None:
            if not current_user.has_permission(Permission.TASK_VIEW_ALL):
                raise HTTPException(status_code=403, detail="Permission denied")
        elif task.get("user_id") != current_user.user_id and not current_user.has_permission(Permission.TASK_VIEW_ALL):
            raise HTTPException(status_code=403, detail="Permission denied")

        return _build_file_response(full_path)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error serving output file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/files/upload/{file_path:path}", tags=["文件服务"])
async def serve_upload_file(file_path: str, current_user: User = Depends(get_current_user_flexible)):
    """提供上传源文件的访问服务（需认证，仅任务所有者或全局查看权限可访问）"""
    try:
        decoded_path = unquote(file_path).lstrip("/")
        full_path = (UPLOAD_DIR / decoded_path).resolve()

        if not full_path.is_relative_to(UPLOAD_DIR.resolve()) or not full_path.is_file():
            logger.warning(f"❌ Access denied or file not found: {full_path}")
            raise HTTPException(status_code=404, detail="File not found or access denied")

        # 归属校验：孤儿文件（任务已被删除的残留源文件）仅全局查看权限可访问
        task = db.get_task_by_upload_path(decoded_path)
        if task is None:
            if not current_user.has_permission(Permission.TASK_VIEW_ALL):
                raise HTTPException(status_code=403, detail="Permission denied")
        elif task.get("user_id") != current_user.user_id and not current_user.has_permission(Permission.TASK_VIEW_ALL):
            raise HTTPException(status_code=403, detail="Permission denied")

        return _build_file_response(full_path)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error serving upload file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


app.include_router(router, prefix="/api/v1")

logger.info(f"📁 File service mounted: /api/v1/files/output -> {OUTPUT_DIR}")
logger.info(f"📁 File service mounted: /api/v1/files/upload -> {UPLOAD_DIR}")

if __name__ == "__main__":
    api_port = int(os.getenv("API_PORT", "8000"))

    logger.info("🚀 Starting MinerU Tianshu API Server...")
    logger.info(f"📖 API Documentation: http://localhost:{api_port}/docs")

    uvicorn.run(app, host="0.0.0.0", port=api_port, log_level="info")
