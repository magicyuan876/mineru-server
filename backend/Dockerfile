# ============================================================================
# MinerU Server - Enterprise AI Data Preprocessing (CUDA 13.0 Edition)
# Optimized for: MinerU 3.4.5 (VLM Support)
# Fixes: Missing botocore, s3transfer, reportlab, and other sub-dependencies
# ============================================================================

# ============================================================================
# 镜像源配置（构建参数）：
#   - 默认使用国内镜像（阿里云 apt / 阿里云 PyPI）
#   - 海外网络: docker buildx build --build-arg APT_MIRROR= --build-arg PIP_MIRROR=https://pypi.org/simple ...
# ============================================================================
ARG APT_MIRROR=mirrors.aliyun.com
ARG PIP_MIRROR=https://mirrors.aliyun.com/pypi/simple/

FROM nvidia/cuda:13.0.2-cudnn-devel-ubuntu24.04 AS base
ARG APT_MIRROR
ARG PIP_MIRROR

# 1. [网络优化] apt 源（APT_MIRROR 为空则保留官方源）+ 抗干扰配置
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s/archive.ubuntu.com/${APT_MIRROR}/g" /etc/apt/sources.list.d/ubuntu.sources && \
        sed -i "s/security.ubuntu.com/${APT_MIRROR}/g" /etc/apt/sources.list.d/ubuntu.sources; \
    fi && \
    echo 'Acquire::Retries "20"; Acquire::http::Timeout "300";' > /etc/apt/apt.conf.d/99custom

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CUDA_HOME=/usr/local/cuda \
    PATH=/usr/local/cuda/bin:$PATH \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH \
    PIP_CACHE_DIR=/root/.cache/pip

# 2. [系统修复] 安装底层库 (Ubuntu 24.04 适配)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-dev python3-pip python3.12-venv \
    git wget curl ffmpeg antiword pandoc poppler-utils \
    libgomp1 libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libgl1 libglx-mesa0 libgstreamer1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 3. [系统修复] 安装中文字体
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-core fonts-noto-cjk fonts-noto-cjk-extra \
    fonts-wqy-zenhei fonts-wqy-microhei fontconfig \
    libreoffice \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# 4. Python 环境配置
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --upgrade --ignore-installed pip "setuptools>=75.0.0" wheel \
    -i ${PIP_MIRROR} --break-system-packages

# -----------------------------------------------------------------------------
# Stage 2: Dependencies Installation
# -----------------------------------------------------------------------------
FROM base AS dependencies
WORKDIR /tmp
COPY backend/requirements.txt /tmp/requirements.txt
ARG PIP_MIRROR

# Step 1: [地基] 锁定科学计算基础包
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "numpy==1.26.4" "pandas>=1.3.0" "psutil" "py-cpuinfo" -i ${PIP_MIRROR} --break-system-packages

# Step 2: [框架] PyTorch 2.10.0+cu130
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch==2.10.0+cu130 torchvision==0.25.0+cu130 --index-url https://download.pytorch.org/whl/cu130 --break-system-packages

# Step 3: [核心业务包] (注意：移除 --no-deps，补全缺失的 botocore/reportlab 等)
# 加入了日志中提示缺失的所有包
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "huggingface-hub<1.0" \
                "mineru[all]>=3.4.5" \
                "transformers==4.57.6" \
                "openai>=1.50.0" \
                "boto3>=1.34.0" \
                "botocore>=1.34.0" \
                "pypdf>=5.1.0" \
                "reportlab" \
                "pdfminer.six>=20251230" \
                "albumentations>=1.4.11" \
                "opencv-python>=4.11.0.86" \
                "scikit-image>=0.25.0" \
                "mineru-vl-utils" \
                "qwen-vl-utils" \
                "doclayout-yolo==0.0.4" \
                "prettytable" \
                "ruamel.yaml" \
                "ujson" \
    -i ${PIP_MIRROR} --break-system-packages

# Step 4: [补全] 安装 requirements.txt 并过滤掉已安装的重型框架
RUN --mount=type=cache,target=/root/.cache/pip \
    sed -i '/torch/d; /nvidia/d; /opencv/d; /numpy/d; /pandas/d; /transformers/d; /mineru/d; /boto3/d; /openai/d; /pypdf/d' /tmp/requirements.txt && \
    pip install -r /tmp/requirements.txt -i ${PIP_MIRROR} --break-system-packages

# Step 5: [重新锁定 PyTorch] 防止上游包降级或替换 torch 版本
# flash_attn 必须与运行时 torch 版本严格匹配，此步确保一致性
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch==2.10.0+cu130 torchvision==0.25.0+cu130 \
    --index-url https://download.pytorch.org/whl/cu130 \
    --break-system-packages

# Step 6: [扩展] FlashAttention (必须在 torch 版本确认后最后安装)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.7.16/flash_attn-2.8.3%2Bcu130torch2.10-cp312-cp312-linux_x86_64.whl --break-system-packages

# Step 7: [最终验证]
RUN python -c "import torch; import flash_attn; import pypdf; import boto3; import botocore; import openai; print('✅ All Backend Dependencies Verified')" && \
    pip show mineru flash-attn | grep -E "^(Name|Version)"

# -----------------------------------------------------------------------------
# Stage 3: Application Runtime
# -----------------------------------------------------------------------------
FROM dependencies AS application
WORKDIR /app
COPY backend/ /app/backend/
COPY pyproject.toml /app/
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/init-models.sh /usr/local/bin/init-models.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/init-models.sh && \
    mkdir -p /app/models /app/data/uploads /app/data/output /app/logs

WORKDIR /app/backend

EXPOSE 8000 8001 8002

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["api", "python", "api_server.py"]
