#!/bin/bash
# Tianshu - Docker Entrypoint Script
# Container startup script for initialization and health checks

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Log functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================================================
# Environment check
# ============================================================================
check_environment() {
    local service_type=$1

    log_info "Checking environment configuration..."

    # Check Python version
    PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
    log_info "Python version: $PYTHON_VERSION"

    # Check CUDA
    if command -v nvidia-smi &> /dev/null; then
        log_success "NVIDIA GPU detected"
        nvidia-smi --query-gpu=gpu_name,driver_version,memory.total --format=csv,noheader
    else
        log_warning "NVIDIA GPU or driver not detected"
    fi

    # Check necessary environment variables (only API Server needs JWT)
    if [ "$service_type" != "worker" ] && [ "$service_type" != "mcp" ]; then
        if [ -z "$JWT_SECRET_KEY" ]; then
            log_error "JWT_SECRET_KEY is not set! Please configure in .env"
            exit 1
        fi

        if [ "$JWT_SECRET_KEY" = "CHANGE_THIS_TO_A_SECURE_RANDOM_STRING_IN_PRODUCTION" ] || [ "$JWT_SECRET_KEY" = "your-secret-key-change-in-production" ]; then
            log_warning "JWT_SECRET_KEY is using default value, must be changed for production!"
        fi
    fi
}

# ============================================================================
# Directory initialization
# ============================================================================
initialize_directories() {
    log_info "Initializing directory structure..."

    mkdir -p /app/models
    mkdir -p /app/data/uploads
    mkdir -p /app/data/output
    mkdir -p /app/logs

    log_success "Directory structure initialized"
}

# ============================================================================
# Config initialization (✅ 核心修复：自动分发配置文件)
# MinerU 3.0 配置文件从 magic-pdf.json 改名为 mineru.json
# 默认路径: ~/mineru.json (由 MINERU_TOOLS_CONFIG_JSON 环境变量控制)
# ============================================================================
setup_mineru_config() {
    log_info "Setting up MinerU configuration (mineru.json)..."

    # 该文件由 download_models.py 生成到共享卷 /app/models 中
    CONFIG_SRC="/app/models/mineru.json"
    CONFIG_FILENAME="${MINERU_TOOLS_CONFIG_JSON:-mineru.json}"
    CONFIG_DEST="/root/${CONFIG_FILENAME}"

    if [ -f "$CONFIG_SRC" ]; then
        cp "$CONFIG_SRC" "${CONFIG_DEST}"
        log_success "mineru.json distributed to ${CONFIG_DEST}"
    else
        log_warning "$CONFIG_SRC not found. MinerU might use default internal settings."
    fi
}

# ============================================================================
# Model initialization
# ============================================================================
initialize_models() {
    log_info "Initializing models..."

    # 检查是否有外部模型卷挂载
    if [ -d "/models-external" ]; then
        # 调用统一的模型初始化脚本
        INIT_SCRIPT="/usr/local/bin/init-models.sh"

        if [ -f "$INIT_SCRIPT" ]; then
            log_info "Running model initialization script: $INIT_SCRIPT"
            bash "$INIT_SCRIPT" || log_warning "Model initialization script failed, continuing..."
        else
            log_warning "Model initialization script not found: $INIT_SCRIPT"
        fi
    else
        log_warning "External models directory (/models-external) not found"
        log_warning "Models will be downloaded on first use"
    fi
}

# ============================================================================
# Model check
# ============================================================================
check_models() {
    log_info "Checking model files..."

    MODEL_PATH=${MODEL_PATH:-/app/models}

    if [ ! -d "$MODEL_PATH" ]; then
        log_warning "Model directory does not exist, will create $MODEL_PATH"
        mkdir -p "$MODEL_PATH"
    fi

    # Check key models
    if [ -d "$MODEL_PATH/sensevoice" ]; then
        log_success "SenseVoice model found"
    else
        log_warning "SenseVoice model not found, audio processing features will be limited"
    fi
}

# ============================================================================
# Database initialization
# ============================================================================
initialize_database() {
    log_info "Checking database..."

    DB_PATH=${DATABASE_PATH:-/app/data/db/mineru_tianshu.db}

    if [ -f "$DB_PATH" ]; then
        log_success "Database exists: $DB_PATH"
    else
        log_info "First run, database will be automatically created"
    fi
}

# ============================================================================
# Health check
# ============================================================================
wait_for_service() {
    local service_url=$1
    local service_name=$2
    local max_retries=30
    local retry_count=0

    log_info "Waiting for $service_name to start..."

    while [ $retry_count -lt $max_retries ]; do
        if curl -f -s "$service_url" > /dev/null 2>&1; then
            log_success "$service_name is ready"
            return 0
        fi

        retry_count=$((retry_count + 1))
        log_info "Waiting... ($retry_count/$max_retries)"
        sleep 2
    done

    log_error "$service_name startup timeout"
    return 1
}

# ============================================================================
# GPU check
# ============================================================================
check_gpu() {
    log_info "Checking GPU availability..."

    # Check PyTorch
    python -c "import torch; print('PyTorch CUDA:', torch.cuda.is_available())" 2>&1 | while read line; do
        log_info "$line"
    done

    # Check device information
    if python -c "import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU')" 2>&1 | grep -q "No GPU"; then
        log_warning "No available GPU device detected"
    else
        GPU_NAME=$(python -c "import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')")
        log_success "GPU device: $GPU_NAME"
    fi
}

# ============================================================================
# Main entry point
# ============================================================================
main() {
    log_info "=========================================="
    log_info "Tianshu Starting..."
    log_info "=========================================="

    # First determine service type
    SERVICE_TYPE=${1:-api}

    # Run checks (pass service type)
    check_environment "$SERVICE_TYPE"
    initialize_directories

    # ✅ 在初始化目录后，执行配置分发
    setup_mineru_config

    initialize_database

    # Initialize models before checking (for worker only)
    if [ "$SERVICE_TYPE" = "worker" ]; then
        initialize_models
    fi

    check_models

    # Execute different checks based on service type

    if [ "$SERVICE_TYPE" = "worker" ]; then
        log_info "Startup type: LitServe Worker"
        check_gpu
        shift  # Remove first argument (service type)
    elif [ "$SERVICE_TYPE" = "mcp" ]; then
        log_info "Startup type: MCP Server"
        shift  # Remove first argument (service type)
    else
        log_info "Startup type: API Server"
        # If first argument is "api", also need to remove it
        if [ "$1" = "api" ]; then
            shift
        fi
    fi

    log_info "=========================================="
    log_success "Initialization complete, starting service..."
    log_info "=========================================="

    # Execute the passed command (at this point $@ no longer contains service type argument)
    exec "$@"
}

# Catch signals for graceful shutdown
trap 'log_warning "Received termination signal, shutting down..."; exit 0' SIGTERM SIGINT

# Execute main function
main "$@"
