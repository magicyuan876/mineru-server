"""
上传文件名净化与校验
防止路径穿越（../、驱动器前缀、Windows 保留字符）与不支持的文件类型落盘
"""

import re
from pathlib import Path

# 平台支持的解析格式全集（文档/图片/音频/视频/生物格式），上传时按此白名单校验
ALLOWED_UPLOAD_EXTENSIONS = {
    # 文档
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".doc",
    ".xls",
    ".ppt",
    ".html",
    ".htm",
    ".txt",
    ".csv",
    ".md",
    ".epub",
    # 图片
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    # 音频
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    # 视频
    ".mp4",
    ".avi",
    ".mkv",
    ".mov",
    ".webm",
    # 生物格式
    ".fasta",
    ".fa",
    ".fna",
    ".ffn",
    ".faa",
    ".frn",
    ".fas",
    ".gb",
    ".gbk",
    ".genbank",
    ".gbff",
    # 压缩包（Worker 解包后按父子任务批量解析）
    ".zip",
}

# Windows 保留字符与控制字符
_UNSAFE_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')

# Windows 保留设备名
_RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class FilenameValidationError(ValueError):
    """文件名不合法（路径穿越嫌疑或类型不支持）"""


def sanitize_filename(name: str) -> str:
    """
    净化用户提供的文件名，使其可安全用于拼接落盘路径

    - 取基名，剥离一切目录成分（../、路径分隔符、驱动器前缀）
    - 剔除 Windows 保留字符、结尾点号与空格、保留设备名
    - 校验扩展名白名单

    Returns:
        安全文件名（不含目录成分）

    Raises:
        FilenameValidationError: 文件名不合法或扩展名不在白名单
    """
    if not name or not isinstance(name, str):
        raise FilenameValidationError("Empty filename")

    # 统一两种分隔符后取基名（PureWindowsPath 能处理 C:\ 与 \ 形式）
    basename = name.replace("\\", "/").split("/")[-1]
    # 剔除保留字符与所有点号开头的穿越成分
    basename = _UNSAFE_CHARS.sub("_", basename).replace("..", "_")
    # 去掉结尾点号与空格（Windows 会自动折叠，避免名实不符）
    basename = basename.rstrip(". ").strip()

    if not basename:
        raise FilenameValidationError("Filename is empty after sanitization")

    stem, _, ext = basename.rpartition(".")
    ext = f".{ext.lower()}" if ext else ""
    if not stem or not ext:
        raise FilenameValidationError("Filename must have a name and an extension")
    if stem.lower() in _RESERVED_NAMES:
        raise FilenameValidationError(f"Reserved filename: {stem}")
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise FilenameValidationError(f"Unsupported file type: {ext}")

    return f"{stem}{ext}"


def ensure_within_directory(file_path: Path, directory: Path) -> Path:
    """
    纵深防御：确认最终路径仍在指定目录内

    Raises:
        FilenameValidationError: 路径逃逸
    """
    resolved = Path(file_path).resolve()
    if not resolved.is_relative_to(Path(directory).resolve()):
        raise FilenameValidationError("Path escapes the upload directory")
    return resolved
