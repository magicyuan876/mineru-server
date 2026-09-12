#!/bin/bash
# Tianshu - 模型初始化脚本（统一版本，自动适配 GPU/CPU）
# 在容器首次启动时从外部卷复制模型到容器内

set -e

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INIT]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[INIT]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[INIT]${NC} $1"
}

# ============================================================================
# 主函数
# ============================================================================
main() {
    log_info "Checking model initialization..."

    # 检测设备模式
    DEVICE_MODE=${DEVICE_MODE:-auto}
    if [ "$DEVICE_MODE" = "auto" ]; then
        if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null 2>&1; then
            log_info "Detected: GPU mode (auto-detection)"
        else
            log_info "Detected: CPU mode (auto-detection)"
        fi
    else
        log_info "Device mode: $DEVICE_MODE (manual configuration)"
    fi

    # 检查初始化标记文件
    if [ -f "/root/.cache/.models_initialized" ]; then
        log_info "Models already initialized, skipping copy"
        return 0
    fi

    # 检查外部模型目录是否存在
    if [ ! -d "/models-external" ]; then
        log_warning "External models directory not found at /models-external"
        log_warning "Models will be downloaded on first use"
        return 0
    fi

    log_info "Copying models from external volume..."
    log_info "This is a one-time operation and may take 5-10 minutes"
    echo ""

    # 创建必要的目录
    mkdir -p /root/.cache/huggingface/hub
    mkdir -p /root/.cache/watermark_models
    mkdir -p /app/models/sensevoice
    mkdir -p /app/models/paraformer

    # 复制 HuggingFace 模型（MinerU）
    if [ -d "/models-external/huggingface/hub" ]; then
        log_info "Copying HuggingFace models (MinerU)..."
        cp -r /models-external/huggingface/hub/* /root/.cache/huggingface/hub/ 2>/dev/null || true
        log_success "HuggingFace models copied"
    fi

    # 复制 SenseVoice 模型
    if [ -d "/models-external/sensevoice" ]; then
        log_info "Copying SenseVoice models..."
        cp -r /models-external/sensevoice/* /app/models/sensevoice/ 2>/dev/null || true
        log_success "SenseVoice models copied"
    fi

    # 复制 Paraformer 模型
    if [ -d "/models-external/paraformer" ]; then
        log_info "Copying Paraformer models..."
        cp -r /models-external/paraformer/* /app/models/paraformer/ 2>/dev/null || true
        log_success "Paraformer models copied"
    fi

    # 复制水印去除模型
    if [ -d "/models-external/watermark_models" ]; then
        log_info "Copying watermark removal models..."
        cp -r /models-external/watermark_models/* /root/.cache/watermark_models/ 2>/dev/null || true
        log_success "Watermark removal models copied"
    fi

    # 创建初始化标记文件
    date -Iseconds > /root/.cache/.models_initialized

    echo ""
    log_success "✅ Models initialized successfully"
    log_info "All models are now ready for use"
}

# 执行主函数
main
