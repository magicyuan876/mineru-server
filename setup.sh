#!/usr/bin/env bash
# ============================================================================
# Tianshu (天枢) - 一键部署脚本（统一入口）
#
# 用法:
#   bash setup.sh                            # 交互式菜单选择部署模式
#   bash setup.sh --mode gpu                 # GPU 标准部署（docker-compose.yml）
#   bash setup.sh --mode pipeline            # 纯 pipeline 部署（并发/显存自动调谐）
#   bash setup.sh --mode cpu                 # Mac CPU 本地开发（.env.cpu + compose.cpu）
#   bash setup.sh --mode native              # 本机原生部署（不用 Docker，Apple Silicon 自动 MPS 加速）
#   bash setup.sh --mode offline-build       # 联网机：构建离线镜像包（docker-images/）
#   bash setup.sh --mode offline-deploy      # 生产机：部署离线镜像包
#   bash setup.sh --mode dev                 # 开发模式（热重载，compose.dev）
#
# 非交互参数:
#   --gpus N          GPU 数量（默认 nvidia-smi -L 自动检测）
#   --concurrency N   每个 GPU 的 Worker 并发数 MAX_CONCURRENT_TASKS（默认 1）
#   --network cn|global  网络环境（cn=国内镜像加速 / global=海外官方源直连，默认交互询问，非交互默认 cn）
#   --yes             跳过全部交互提问，未指定的配置保持 .env 默认值
#   --dry-run         只生成配置文件并打印将执行的操作，不构建、不启动
#   -h, --help        显示帮助
#
# 示例:
#   bash setup.sh --mode pipeline --gpus 2 --concurrency 2 --yes
#   bash setup.sh --mode gpu --dry-run       # 预览 .env 与执行计划
#   bash setup.sh --mode cpu --yes           # Mac 上一键 CPU 开发环境
#   bash setup.sh --mode native              # Mac 原生运行（MPS 加速，性能优于 Docker CPU）
# ============================================================================

set -euo pipefail

# 镜像全部经 --load 进本地，不推仓库，buildx 默认附带的 provenance attestation 没有用处；
# 它会把产物变成 OCI index，走上更复杂的导出路径。关掉它，导出直接落普通 manifest。
export BUILDX_NO_DEFAULT_ATTESTATIONS=1

# ----------------------------------------------------------------------------
# 输出辅助
# ----------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

# ----------------------------------------------------------------------------
# 参数解析
# ----------------------------------------------------------------------------
MODE=""
OPT_GPUS=""
OPT_CONCURRENCY=""
OPT_NETWORK=""
ASSUME_YES=0
DRY_RUN=0

while [ $# -gt 0 ]; do
    case "$1" in
        --mode)
            MODE="${2:-}"
            shift 2
            ;;
        --network)
            OPT_NETWORK="${2:-}"
            shift 2
            ;;
        --gpus | -g)
            OPT_GPUS="${2:-}"
            shift 2
            ;;
        --concurrency | -c)
            OPT_CONCURRENCY="${2:-}"
            shift 2
            ;;
        --yes | -y)
            ASSUME_YES=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            log_error "未知参数: $1"
            echo "运行 'bash setup.sh --help' 查看用法。"
            exit 1
            ;;
    esac
done

# 进入脚本所在目录（正常模式为仓库根目录；offline-deploy 为离线包目录）
cd "$(dirname "$0")" || exit 1

# 是否进行交互提问：终端 + 未指定 --yes + 非 dry-run
INTERACTIVE=0
if [ -t 0 ] && [ "$ASSUME_YES" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    INTERACTIVE=1
fi

# 环境配置文件（cpu 模式切换为 .env.cpu）
ENV_FILE=".env"

# 调谐常量
MIN_VRAM_PER_WORKER=6
RAM_PER_WORKER_GB=8
MAX_RAM_PERCENT=25
MIN_MEM_LIMIT_GB=16

# ----------------------------------------------------------------------------
# 可移植工具
# ----------------------------------------------------------------------------

# macOS 的 BSD sed 需要 -i ''，GNU sed 需要 -i
sed_i() {
    if [ "$(uname)" = "Darwin" ]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

# 交互提问：ask "问题" "默认值"，结果写入 REPLY；非交互时直接取默认值
REPLY=""
ask() {
    local prompt="$1"
    local default="$2"
    local input=""
    if [ "$INTERACTIVE" -eq 0 ]; then
        REPLY="$default"
        return 0
    fi
    printf "${BLUE}[?]${NC} %s [%s]: " "$prompt" "$default"
    read -r input
    REPLY="${input:-$default}"
}

# 是非提问：ask_yn "问题" "Y|N"，默认值为 Y 时非交互返回 0（是）
ask_yn() {
    local prompt="$1"
    local default="$2"
    local input=""
    if [ "$INTERACTIVE" -eq 0 ]; then
        [ "$default" = "Y" ]
        return
    fi
    printf "${BLUE}[?]${NC} %s [%s]: " "$prompt" "$default"
    read -r input
    input="${input:-$default}"
    case "$input" in
        [Yy]*) return 0 ;;
        *) return 1 ;;
    esac
}

# ----------------------------------------------------------------------------
# 网络环境选择（决定 apt / pip / npm 镜像源）
# ----------------------------------------------------------------------------
# cn:     国内镜像加速（阿里云 apt + 清华 PyPI + npmmirror）
# global: 海外/代理直连（官方源）
NETWORK_ENV=""
APT_MIRROR=""
PIP_MIRROR=""
NPM_REGISTRY=""

choose_network() {
    NETWORK_ENV="$OPT_NETWORK"
    if [ -z "$NETWORK_ENV" ]; then
        if [ "$INTERACTIVE" -eq 1 ]; then
            echo ""
            echo "  网络环境: 1) 国内（镜像加速，默认）  2) 海外/代理（官方源直连）"
            ask "请选择网络环境 [1/2]" "1"
            case "$REPLY" in
                2 | global | overseas) NETWORK_ENV="global" ;;
                *) NETWORK_ENV="cn" ;;
            esac
        else
            NETWORK_ENV="cn"
        fi
    fi

    case "$NETWORK_ENV" in
        cn)
            APT_MIRROR="mirrors.aliyun.com"
            PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
            NPM_REGISTRY="https://registry.npmmirror.com"
            ;;
        global)
            APT_MIRROR=""
            PIP_MIRROR="https://pypi.org/simple"
            NPM_REGISTRY="https://registry.npmjs.org"
            ;;
        *)
            log_error "未知网络环境: ${NETWORK_ENV}（可选: cn / global）"
            exit 1
            ;;
    esac
    export APT_MIRROR PIP_MIRROR NPM_REGISTRY
    log_info "网络环境: ${NETWORK_ENV}（apt=${APT_MIRROR:-官方源} / pip=${PIP_MIRROR} / npm=${NPM_REGISTRY}）"
}

# ----------------------------------------------------------------------------
# Docker Compose 命令
# ----------------------------------------------------------------------------
DC=()

detect_compose() {
    if docker compose version > /dev/null 2>&1; then
        DC=(docker compose)
    elif command -v docker-compose > /dev/null 2>&1; then
        DC=(docker-compose)
    elif [ "$DRY_RUN" -eq 1 ]; then
        DC=(docker compose) # dry-run 仅用于打印
    else
        log_error "未找到 Docker Compose，安装指南: https://docs.docker.com/compose/install/"
        exit 1
    fi
}

# 启用 Redis 时 compose 命令附加 --profile redis（保证 stop/logs 等也带上）
add_redis_profile() {
    if [ -f "$ENV_FILE" ] && grep -qE '^REDIS_QUEUE_ENABLED=true' "$ENV_FILE"; then
        DC+=(--profile redis)
        log_info "Redis 队列已启用，compose 附加 --profile redis"
    fi
}

# ----------------------------------------------------------------------------
# .env 读写
# ----------------------------------------------------------------------------
get_env_key() {
    local key="$1"
    if [ ! -f "$ENV_FILE" ]; then
        return 0
    fi
    grep -E "^${key}=" "$ENV_FILE" | head -n1 | cut -d= -f2- || true
}

set_env_key() {
    local key="$1"
    local val="$2"
    if grep -qE "^${key}=" "$ENV_FILE"; then
        sed_i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
    fi
}

# ----------------------------------------------------------------------------
# 环境探测
# ----------------------------------------------------------------------------
detect_gpu_count() {
    local n
    n=$(nvidia-smi -L 2> /dev/null | grep -c '^GPU ' || true)
    echo "${n:-0}"
}

# 全机最小单卡显存（GB），混插显卡时按最小卡规划预算
detect_min_vram_gb() {
    local mib
    mib=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2> /dev/null \
        | tr -d ' ' | sort -n | head -n1 || true)
    if [ -z "$mib" ]; then
        echo 0
    else
        echo $((mib / 1024))
    fi
}

detect_total_ram_gb() {
    local kb=""
    local bytes=""
    if [ -r /proc/meminfo ]; then
        kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo || true)
    fi
    if [ -n "$kb" ]; then
        echo $((kb / 1024 / 1024))
        return 0
    fi
    # macOS 回退
    if command -v sysctl > /dev/null 2>&1; then
        bytes=$(sysctl -n hw.memsize 2> /dev/null || true)
        if [ -n "$bytes" ]; then
            echo $((bytes / 1024 / 1024 / 1024))
            return 0
        fi
    fi
    echo 0
}

detect_server_ip() {
    local ip=""
    if command -v ip > /dev/null 2>&1; then
        ip=$(ip route get 1.1.1.1 2> /dev/null \
            | awk '{for (i = 1; i <= NF; i++) if ($i == "src") print $(i + 1)}' | head -n1 || true)
    fi
    if [ -z "$ip" ] && command -v hostname > /dev/null 2>&1; then
        ip=$(hostname -I 2> /dev/null | awk '{print $1}' || true)
    fi
    # macOS 回退
    if [ -z "$ip" ] && command -v ipconfig > /dev/null 2>&1; then
        ip=$(ipconfig getifaddr en0 2> /dev/null || true)
    fi
    echo "$ip"
}

container_running() {
    docker ps --filter "name=$1" --filter "status=running" --format '{{.Names}}' 2> /dev/null \
        | grep -q "$1"
}

# ----------------------------------------------------------------------------
# 依赖检查（GPU 模式）
# ----------------------------------------------------------------------------
check_dependencies() {
    local strict_gpu="$1" # 1 = 无 GPU 直接报错（pipeline 模式）
    log_info "检查系统依赖..."

    if ! command -v docker > /dev/null 2>&1; then
        log_error "未安装 Docker，安装指南: https://docs.docker.com/get-docker/"
        exit 1
    fi
    log_success "Docker: $(docker --version)"
    detect_compose
    log_success "Compose: $("${DC[@]}" version 2> /dev/null | head -n1)"

    if ! command -v nvidia-smi > /dev/null 2>&1; then
        if [ "$strict_gpu" -eq 1 ]; then
            log_error "未找到 nvidia-smi，MinerU pipeline 引擎必须使用 GPU。"
            log_error "纯 CPU 环境请改用: bash setup.sh --mode cpu"
            exit 1
        fi
        log_warning "未检测到 NVIDIA GPU，将以 CPU 方式运行（性能大幅下降）"
        return 0
    fi
    log_success "NVIDIA 驱动正常:"
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader || true

    if docker run --rm --gpus all nvidia/cuda:12.6.2-base-ubuntu22.04 nvidia-smi > /dev/null 2>&1; then
        log_success "NVIDIA Container Toolkit 工作正常"
    elif [ "$strict_gpu" -eq 1 ]; then
        log_error "Docker 无法访问 GPU（NVIDIA Container Toolkit 缺失或配置错误）。"
        log_error "安装指南: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
        exit 1
    else
        log_warning "NVIDIA Container Toolkit 未正确配置，GPU 容器可能无法启动"
        log_info "安装指南: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
    fi
}

# ----------------------------------------------------------------------------
# 环境配置
# ----------------------------------------------------------------------------
prepare_env() {
    # 示例文件名与 ENV_FILE 派生一致：.env -> .env.example，.env.cpu -> .env.cpu.example
    local example_file="${ENV_FILE}.example"
    if [ ! -f "$ENV_FILE" ]; then
        if [ ! -f "$example_file" ]; then
            log_error "$example_file 不存在，无法创建 $ENV_FILE"
            exit 1
        fi
        cp "$example_file" "$ENV_FILE"
        log_success "已从 $example_file 创建 $ENV_FILE"
    else
        log_info "$ENV_FILE 已存在，仅更新部署相关键"
    fi
}

# 生成随机密钥（优先 openssl，缺失时回退 /dev/urandom）
gen_random_hex() {
    local bytes="${1:-32}"
    if command -v openssl > /dev/null 2>&1; then
        openssl rand -hex "$bytes"
    else
        cat /dev/urandom | LC_ALL=C tr -dc 'a-f0-9' | head -c $((bytes * 2))
    fi
}

# JWT_SECRET_KEY 为空或为已知占位符时自动生成
ensure_jwt_secret() {
    local jwt
    jwt=$(get_env_key JWT_SECRET_KEY)
    case "$jwt" in
        "" | your-secret-key-change-in-production | dev-secret-key-change-in-production | cpu-dev-secret-key-change-in-production | temp-secret-key | CHANGE_THIS_TO_A_SECURE_RANDOM_STRING_IN_PRODUCTION)
            local secret
            secret=$(gen_random_hex 32)
            if [ -n "$secret" ]; then
                set_env_key JWT_SECRET_KEY "$secret"
                log_success "JWT_SECRET_KEY 已自动生成（openssl rand -hex 32）"
            else
                log_warning "未找到 openssl，请手动修改 $ENV_FILE 中的 JWT_SECRET_KEY"
            fi
            ;;
        *)
            log_info "JWT_SECRET_KEY 已自定义，保持不变"
            ;;
    esac
}

# RustFS 访问密钥为空或为已知占位符/默认凭据时自动生成
ensure_rustfs_keys() {
    local rustfs_enabled
    rustfs_enabled=$(get_env_key RUSTFS_ENABLED)
    if [ "$rustfs_enabled" = "false" ]; then
        return 0
    fi

    local access_key
    access_key=$(get_env_key RUSTFS_ACCESS_KEY)
    case "$access_key" in
        "" | rustfsadmin | CHANGE_THIS_TO_A_RANDOM_VALUE)
            set_env_key RUSTFS_ACCESS_KEY "$(gen_random_hex 16)"
            log_success "RUSTFS_ACCESS_KEY 已自动生成（openssl rand -hex 16）"
            ;;
        *)
            log_info "RUSTFS_ACCESS_KEY 已自定义，保持不变"
            ;;
    esac

    local secret_key
    secret_key=$(get_env_key RUSTFS_SECRET_KEY)
    case "$secret_key" in
        "" | rustfsadmin | CHANGE_THIS_TO_A_RANDOM_VALUE)
            set_env_key RUSTFS_SECRET_KEY "$(gen_random_hex 32)"
            log_success "RUSTFS_SECRET_KEY 已自动生成（openssl rand -hex 32）"
            ;;
        *)
            log_info "RUSTFS_SECRET_KEY 已自定义，保持不变"
            ;;
    esac
}

# 启用 Redis 队列时，REDIS_PASSWORD 为空或占位符则自动生成
ensure_redis_password() {
    local redis_enabled
    redis_enabled=$(get_env_key REDIS_QUEUE_ENABLED)
    if [ "$redis_enabled" != "true" ]; then
        return 0
    fi

    local redis_password
    redis_password=$(get_env_key REDIS_PASSWORD)
    case "$redis_password" in
        "" | CHANGE_THIS_TO_A_RANDOM_VALUE)
            set_env_key REDIS_PASSWORD "$(gen_random_hex 24)"
            log_success "REDIS_PASSWORD 已自动生成（openssl rand -hex 24）"
            ;;
        *)
            log_info "REDIS_PASSWORD 已自定义，保持不变"
            ;;
    esac
}

# 初始管理员密码为空或占位符时自动生成（首次部署后端强制要求）
# 不明文回显：部署完成后提示用户到 $ENV_FILE 查看
ensure_admin_password() {
    local admin_password
    admin_password=$(get_env_key TIANSHU_ADMIN_PASSWORD)
    case "$admin_password" in
        "" | CHANGE_THIS_TO_A_RANDOM_VALUE)
            set_env_key TIANSHU_ADMIN_PASSWORD "$(gen_random_hex 16)"
            log_success "TIANSHU_ADMIN_PASSWORD 已自动生成（写入 ${ENV_FILE}，请部署后查看并妥善保存）"
            ;;
        *)
            log_info "TIANSHU_ADMIN_PASSWORD 已自定义，保持不变"
            ;;
    esac
}

# GPU/pipeline 模式的交互式提问（--yes / dry-run / 非终端时保持 .env 默认值）
interactive_configure() {
    [ "$INTERACTIVE" -eq 1 ] || return 0

    echo ""
    log_info "部署配置（回车使用默认值）"

    local detected
    detected=$(detect_gpu_count)
    local gpu_default=1
    [ "$detected" -gt 0 ] && gpu_default="$detected"
    ask "GPU 数量" "$gpu_default"
    OPT_GPUS="$REPLY"

    ask "每个 GPU 的 Worker 并发数（MAX_CONCURRENT_TASKS）" "1"
    OPT_CONCURRENCY="$REPLY"

    echo "  模型下载源: 1) auto（自动）  2) huggingface  3) modelscope（国内推荐）"
    ask "请选择模型源" "1"
    case "$REPLY" in
        2 | huggingface) set_env_key MODEL_DOWNLOAD_SOURCE huggingface ;;
        3 | modelscope) set_env_key MODEL_DOWNLOAD_SOURCE modelscope ;;
        *) set_env_key MODEL_DOWNLOAD_SOURCE auto ;;
    esac

    if ask_yn "是否启用 Redis 队列（高并发场景推荐）" "N"; then
        set_env_key REDIS_QUEUE_ENABLED true
    else
        set_env_key REDIS_QUEUE_ENABLED false
    fi

    if ask_yn "是否启用 RustFS 对象存储（解析结果图片外链）" "Y"; then
        set_env_key RUSTFS_ENABLED true
        local ip
        local front_port
        ip=$(detect_server_ip)
        front_port=$(get_env_key FRONTEND_PORT)
        front_port="${front_port:-80}"
        # RustFS 端口仅绑定回环，图片统一经前端 nginx /s3/ 反代访问
        ask "RustFS 公网访问地址（经前端 nginx /s3/ 反代，需浏览器可达）" "http://${ip:-127.0.0.1}:${front_port}/s3"
        set_env_key RUSTFS_PUBLIC_URL "$REPLY"
    else
        set_env_key RUSTFS_ENABLED false
    fi

    local api_default
    local front_default
    api_default=$(get_env_key API_PORT)
    api_default="${api_default:-8000}"
    front_default=$(get_env_key FRONTEND_PORT)
    front_default="${front_default:-80}"
    ask "API 端口" "$api_default"
    set_env_key API_PORT "$REPLY"
    set_env_key VITE_API_BASE_URL "http://localhost:${REPLY}"
    ask "前端端口" "$front_default"
    set_env_key FRONTEND_PORT "$REPLY"
    echo ""
}

# 自动调谐：并发/显存/内存按 GPU 资源自动计算
tune_env() {
    local detected_gpus
    local min_vram
    detected_gpus=$(detect_gpu_count)
    min_vram=$(detect_min_vram_gb)

    ensure_jwt_secret
    ensure_rustfs_keys
    ensure_redis_password
    ensure_admin_password

    # --- GPU 数量 -----------------------------------------------------------
    local gpu_count
    if [ -n "$OPT_GPUS" ]; then
        gpu_count="$OPT_GPUS"
        set_env_key GPU_COUNT "$gpu_count"
        log_success "GPU_COUNT = ${gpu_count}（--gpus 指定）"
    elif [ "$detected_gpus" -gt 0 ]; then
        gpu_count="$detected_gpus"
        set_env_key GPU_COUNT "$gpu_count"
        log_success "GPU_COUNT = ${gpu_count}（自动检测）"
    else
        gpu_count=$(get_env_key GPU_COUNT)
        gpu_count="${gpu_count:-1}"
        log_warning "未检测到 GPU，GPU_COUNT 保持 ${gpu_count}"
    fi

    # --- Worker 并发 --------------------------------------------------------
    # litserve_worker.py 只读 MAX_CONCURRENT_TASKS，这是控制并发的唯一入口
    local concurrency
    if [ -n "$OPT_CONCURRENCY" ]; then
        concurrency="$OPT_CONCURRENCY"
    else
        concurrency=$(get_env_key MAX_CONCURRENT_TASKS)
        concurrency="${concurrency:-1}"
    fi
    if ! [ "$concurrency" -ge 1 ] 2> /dev/null; then
        log_error "非法并发数: ${concurrency}"
        exit 1
    fi
    set_env_key MAX_CONCURRENT_TASKS "$concurrency"
    log_success "MAX_CONCURRENT_TASKS = ${concurrency}（每卡 Worker 进程数）"

    # --- 每 Worker 显存预算 --------------------------------------------------
    # MinerU 按 MINERU_VIRTUAL_VRAM_SIZE 规划 batch，同卡多进程必须平分显存
    local vram
    if [ "$min_vram" -gt 0 ]; then
        vram=$((min_vram / concurrency))
        if [ "$vram" -lt "$MIN_VRAM_PER_WORKER" ]; then
            vram="$MIN_VRAM_PER_WORKER"
        fi
    else
        vram=$(get_env_key MINERU_VIRTUAL_VRAM_SIZE)
        vram="${vram:-8}"
    fi
    set_env_key MINERU_VIRTUAL_VRAM_SIZE "$vram"
    log_success "MINERU_VIRTUAL_VRAM_SIZE = ${vram} GB / worker（单卡 ${min_vram} GB）"

    if [ "$min_vram" -gt 0 ] && [ $((vram * concurrency)) -gt "$min_vram" ]; then
        log_warning "显存超配（${vram} x ${concurrency} > ${min_vram} GB），如遇 CUDA OOM 请降低并发"
    fi

    # --- RustFS 公网地址 -----------------------------------------------------
    # 解析结果中的图片会改写为该地址，必须浏览器可达；
    # RustFS 端口仅绑定回环，默认经前端 nginx /s3/ 路径反代
    local rustfs_enabled
    rustfs_enabled=$(get_env_key RUSTFS_ENABLED)
    if [ "$rustfs_enabled" != "false" ]; then
        local rustfs_url
        local front_port
        local server_ip
        rustfs_url=$(get_env_key RUSTFS_PUBLIC_URL)
        front_port=$(get_env_key FRONTEND_PORT)
        front_port="${front_port:-80}"
        server_ip=$(detect_server_ip)
        case "$rustfs_url" in
            "" | *192.168.1.100* | http://localhost/s3 | http://127.0.0.1/s3)
                if [ -n "$server_ip" ]; then
                    set_env_key RUSTFS_PUBLIC_URL "http://${server_ip}:${front_port}/s3"
                    log_success "RUSTFS_PUBLIC_URL = http://${server_ip}:${front_port}/s3（经前端 nginx 反代）"
                else
                    log_warning "未能探测服务器 IP，请手动设置 RUSTFS_PUBLIC_URL，否则解析结果的图片无法加载"
                fi
                ;;
            *)
                log_info "RUSTFS_PUBLIC_URL 已配置（${rustfs_url}），保持不变"
                ;;
        esac
    fi

    # --- Worker 内存上限 -----------------------------------------------------
    # cgroup 硬上限而非预留：随 worker 进程数放大，防止失控进程拖垮宿主机
    local total_ram
    local workers
    local mem_limit_gb=""
    total_ram=$(detect_total_ram_gb)
    workers=$((gpu_count * concurrency))

    if [ "$total_ram" -gt 0 ]; then
        local want=$((workers * RAM_PER_WORKER_GB))
        local cap=$((total_ram * MAX_RAM_PERCENT / 100))
        if [ "$want" -le "$cap" ]; then
            mem_limit_gb="$want"
        else
            mem_limit_gb="$cap"
            log_warning "${workers} 个 Worker 期望 ${want}G，但主机内存的 ${MAX_RAM_PERCENT}% 仅为 ${cap}G，已按上限收敛"
        fi
        if [ "$mem_limit_gb" -lt "$MIN_MEM_LIMIT_GB" ]; then
            mem_limit_gb="$MIN_MEM_LIMIT_GB"
        fi
    fi

    if [ -n "$mem_limit_gb" ]; then
        local mem_res_gb=$((mem_limit_gb / 4))
        if [ "$mem_res_gb" -lt 8 ]; then
            mem_res_gb=8
        fi
        set_env_key WORKER_MEMORY_LIMIT "${mem_limit_gb}G"
        set_env_key WORKER_MEMORY_RESERVATION "${mem_res_gb}G"
        log_success "WORKER_MEMORY_LIMIT = ${mem_limit_gb}G（主机内存 ${total_ram}G，${workers} 个 Worker 进程）"
        log_info "该值为上限而非预留，实际占用可用 docker stats tianshu-worker 观察"
    else
        log_warning "无法读取主机内存，WORKER_MEMORY_LIMIT 保持 $(get_env_key WORKER_MEMORY_LIMIT)"
        log_warning "请按每 Worker 约 ${RAM_PER_WORKER_GB}G（当前 ${workers} 个）手动估算"
    fi
}

create_directories() {
    log_info "创建宿主机目录..."
    mkdir -p models \
        input output \
        data/uploads data/output data/db \
        logs/backend logs/worker logs/mcp logs/scheduler
    # 容器以非 root 用户（tianshu, UID 10001）运行，需保证数据/日志目录对容器可写；
    # 权限不足时容器 entrypoint 会给出明确报错（best-effort，失败不中断）
    chmod -R a+rwX data logs input output 2> /dev/null || true
    log_success "目录就绪"
}

# ----------------------------------------------------------------------------
# 构建 / 启动 / 验证（GPU 类模式共用）
# ----------------------------------------------------------------------------
build_images() {
    log_info "构建镜像（首次需拉取大量依赖，约 10-30 分钟）..."
    DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 "${DC[@]}" build --parallel
    log_success "镜像构建完成"
}

start_services() {
    log_info "启动服务..."
    "${DC[@]}" up -d
    log_success "容器已启动"
    log_info "init-models 首次运行会下载模型，worker 会等待其完成"
}

# 健康检查：轮询 API 180s + 前端 nginx 代理路径（端口读 $ENV_FILE）
verify_deployment() {
    local api_port
    local frontend_port
    local rc=0
    api_port=$(get_env_key API_PORT)
    api_port="${api_port:-8000}"
    frontend_port=$(get_env_key FRONTEND_PORT)
    frontend_port="${frontend_port:-80}"

    log_info "等待 API 就绪（最长 180s）..."
    local ok=0
    local waited=0
    while [ "$waited" -lt 180 ]; do
        if curl -fsS "http://localhost:${api_port}/api/v1/health" > /dev/null 2>&1; then
            ok=1
            break
        fi
        sleep 3
        waited=$((waited + 3))
    done

    if [ "$ok" -eq 1 ]; then
        log_success "API 健康（端口 ${api_port}）"
    else
        log_error "API 健康检查超时，排查: ${DC[*]} logs backend"
        return 1
    fi

    # 浏览器经前端 nginx 反代访问 API，与上面的直连路径不同，需单独验证
    if curl -fsS "http://localhost:${frontend_port}/api/v1/health" > /dev/null 2>&1; then
        log_success "前端 -> API 代理健康（端口 ${frontend_port}）"
    else
        log_error "nginx 无法访问 API：端口 ${frontend_port} 的 /api/v1/health 失败"
        log_error "检查 frontend/Dockerfile 中 'location /api/' 的 proxy_pass 配置"
        rc=1
    fi

    if container_running tianshu-worker; then
        log_success "Worker 容器运行中"
    else
        log_warning "Worker 尚未就绪（在等待 init-models 下载模型）"
        log_warning "跟踪进度: ${DC[*]} logs -f init-models worker"
    fi

    return "$rc"
}

show_info() {
    local api_port
    local frontend_port
    local gpu_count
    local concurrency
    local server_ip
    api_port=$(get_env_key API_PORT)
    api_port="${api_port:-8000}"
    frontend_port=$(get_env_key FRONTEND_PORT)
    frontend_port="${frontend_port:-80}"
    gpu_count=$(get_env_key GPU_COUNT)
    gpu_count="${gpu_count:-1}"
    concurrency=$(get_env_key MAX_CONCURRENT_TASKS)
    concurrency="${concurrency:-1}"
    server_ip=$(detect_server_ip)
    server_ip="${server_ip:-localhost}"

    echo ""
    log_success "=========================================="
    log_success " Tianshu (天枢) 部署完成"
    log_success "=========================================="
    echo ""
    echo "  Web UI:   http://${server_ip}:${frontend_port}"
    echo "  API 文档: http://${server_ip}:${api_port}/docs"
    echo "  并发能力: ${gpu_count} GPU x ${concurrency} Worker = $((gpu_count * concurrency)) 并发任务"
    echo "  资源预算: 每 Worker $(get_env_key MINERU_VIRTUAL_VRAM_SIZE)G 显存，内存上限 $(get_env_key WORKER_MEMORY_LIMIT)（非预留）"
    echo ""
    echo "  查看日志: ${DC[*]} logs -f"
    echo "  查看状态: ${DC[*]} ps"
    echo "  停止服务: ${DC[*]} down"
    echo ""
    log_warning "管理员账号: $(get_env_key TIANSHU_ADMIN_USERNAME)（初始密码见 ${ENV_FILE} 中 TIANSHU_ADMIN_PASSWORD，请妥善保存）"
    echo ""
}

# ----------------------------------------------------------------------------
# dry-run 摘要
# ----------------------------------------------------------------------------
dry_run_summary() {
    local api_port
    local frontend_port
    api_port=$(get_env_key API_PORT 2> /dev/null || true)
    api_port="${api_port:-8000}"
    frontend_port=$(get_env_key FRONTEND_PORT 2> /dev/null || true)
    frontend_port="${frontend_port:-80}"

    echo ""
    log_success "================= DRY-RUN 摘要 ================="
    log_info "模式: ${MODE}"
    if [ -f "$ENV_FILE" ]; then
        log_info "配置文件 ${ENV_FILE} 已生成/更新，关键项:"
        echo "    GPU_COUNT                 = $(get_env_key GPU_COUNT)"
        echo "    MAX_CONCURRENT_TASKS      = $(get_env_key MAX_CONCURRENT_TASKS)"
        echo "    MINERU_VIRTUAL_VRAM_SIZE  = $(get_env_key MINERU_VIRTUAL_VRAM_SIZE)"
        echo "    WORKER_MEMORY_LIMIT       = $(get_env_key WORKER_MEMORY_LIMIT)"
        echo "    WORKER_MEMORY_RESERVATION = $(get_env_key WORKER_MEMORY_RESERVATION)"
        echo "    REDIS_QUEUE_ENABLED       = $(get_env_key REDIS_QUEUE_ENABLED)"
        echo "    RUSTFS_ENABLED            = $(get_env_key RUSTFS_ENABLED)"
        echo "    RUSTFS_PUBLIC_URL         = $(get_env_key RUSTFS_PUBLIC_URL)"
        echo "    MODEL_DOWNLOAD_SOURCE     = $(get_env_key MODEL_DOWNLOAD_SOURCE)"
        echo "    API_PORT / FRONTEND_PORT  = ${api_port} / ${frontend_port}"
        echo "    JWT_SECRET_KEY            = $(get_env_key JWT_SECRET_KEY | cut -c1-8)...（已生成，仅显示前 8 位）"
        echo "    TIANSHU_ADMIN_USERNAME    = $(get_env_key TIANSHU_ADMIN_USERNAME)（初始密码见 ${ENV_FILE}）"
    fi
    log_info "将创建目录: models input output data/{uploads,output,db} logs/{backend,worker,mcp,scheduler}"
    if [ "${1:-}" = "compose" ]; then
        log_info "将执行构建: ${DC[*]} build --parallel"
        log_info "将启动服务: ${DC[*]} up -d"
        log_info "健康检查:   http://localhost:${api_port}/api/v1/health（最长 180s）"
        log_info "            http://localhost:${frontend_port}/api/v1/health（前端 nginx 代理）"
    fi
    log_warning "dry-run 模式：未执行依赖检查、构建与启动"
    echo ""
}

# ----------------------------------------------------------------------------
# 模式：gpu / pipeline
# ----------------------------------------------------------------------------
deploy_gpu_mode() {
    MODE="$1"
    local strict=0
    [ "$MODE" = "pipeline" ] && strict=1

    if [ "$DRY_RUN" -eq 1 ]; then
        detect_compose
        if ! command -v nvidia-smi > /dev/null 2>&1; then
            if [ "$strict" -eq 1 ]; then
                log_warning "dry-run：未检测到 GPU（正式执行 pipeline 模式时会直接报错退出）"
            else
                log_warning "dry-run：未检测到 GPU，将使用 .env 默认值继续预览"
            fi
        fi
    else
        check_dependencies "$strict"
    fi

    # compose 组合
    DC+=(-f docker-compose.yml)
    [ "$MODE" = "pipeline" ] && DC+=(-f docker-compose.pipeline.yml)

    prepare_env
    interactive_configure
    tune_env
    add_redis_profile

    if [ "$DRY_RUN" -eq 1 ]; then
        dry_run_summary compose
        return 0
    fi

    create_directories
    build_images
    start_services
    if ! verify_deployment; then
        log_warning "部署完成但存在告警，请查看上方信息"
    fi
    show_info
}

# ----------------------------------------------------------------------------
# 模式：cpu（Mac Apple Silicon 本地开发）
# ----------------------------------------------------------------------------
deploy_cpu() {
    MODE="cpu"
    ENV_FILE=".env.cpu"

    log_info "CPU 本地开发模式（Dockerfile.cpu，linux/amd64）"

    if [ "$DRY_RUN" -eq 0 ]; then
        if ! command -v docker > /dev/null 2>&1; then
            log_error "未安装 Docker，请安装 Docker Desktop for Mac: https://www.docker.com/products/docker-desktop"
            exit 1
        fi
        if ! docker info > /dev/null 2>&1; then
            log_error "Docker 未运行，请先启动 Docker Desktop"
            exit 1
        fi
        log_success "Docker 正常: $(docker --version)"
    fi
    detect_compose

    if [ "$(uname -m)" = "arm64" ]; then
        log_info "检测到 Apple Silicon (arm64)"
        log_warning "请确认 Docker Desktop 已启用 Rosetta 2 模拟:"
        log_warning "  Settings → General → Use Rosetta for x86_64/amd64 emulation"
    fi

    # 离线模型确认
    if [ ! -d "./models-offline" ] || [ -z "$(ls -A ./models-offline 2> /dev/null)" ]; then
        log_warning "未找到离线模型目录 ./models-offline（或为空）"
        log_info "可先下载: python3 backend/download_models.py --output ./models-offline"
        if [ "$INTERACTIVE" -eq 1 ]; then
            if ! ask_yn "是否在无离线模型的情况下继续（运行时联网下载）" "N"; then
                log_error "已取消"
                exit 1
            fi
        else
            log_warning "非交互模式：继续执行，模型将在运行时按需下载"
        fi
    else
        log_success "离线模型已就绪: ./models-offline"
    fi

    # compose 组合
    DC+=(-f docker-compose.cpu.yml --env-file .env.cpu)

    # 生成 .env.cpu 并强制 CPU 配置
    prepare_env
    set_env_key ACCELERATOR cpu
    set_env_key CUDA_VISIBLE_DEVICES ""
    set_env_key MODEL_DOWNLOAD_SOURCE local
    set_env_key HF_OFFLINE 1
    ensure_jwt_secret
    ensure_rustfs_keys
    ensure_admin_password
    log_success ".env.cpu 已配置（ACCELERATOR=cpu / CUDA_VISIBLE_DEVICES=空 / MODEL_DOWNLOAD_SOURCE=local / HF_OFFLINE=1）"

    if [ "$DRY_RUN" -eq 1 ]; then
        dry_run_summary
        log_info "将执行构建: docker buildx build --platform linux/amd64 -f backend/Dockerfile.cpu --build-arg APT_MIRROR=... --build-arg PIP_MIRROR=... -t tianshu-backend-cpu:latest --load ."
        log_info "将启动服务: ${DC[*]} up -d"
        log_info "健康检查:   Backend /api/v1/health、Worker /health、前端 /、RustFS /health（端口读 .env.cpu）"
        return 0
    fi

    create_directories

    # 构建镜像
    log_info "构建后端 CPU 镜像（linux/amd64，首次约 30-60 分钟）..."
    DOCKER_BUILDKIT=1 docker buildx build \
        --platform linux/amd64 \
        --file backend/Dockerfile.cpu \
        --build-arg APT_MIRROR="$APT_MIRROR" \
        --build-arg PIP_MIRROR="$PIP_MIRROR" \
        --tag tianshu-backend-cpu:latest \
        --load \
        .
    log_success "后端 CPU 镜像构建完成: tianshu-backend-cpu:latest"

    if ! docker images | grep -q "tianshu-frontend"; then
        log_info "构建前端镜像..."
        DOCKER_BUILDKIT=1 docker buildx build \
            --platform linux/amd64 \
            --file frontend/Dockerfile \
            --build-arg NPM_REGISTRY="$NPM_REGISTRY" \
            --tag tianshu-frontend:latest \
            --load \
            .
        log_success "前端镜像构建完成"
    else
        log_info "前端镜像已存在，跳过（重建: docker rmi tianshu-frontend:latest 后重跑）"
    fi

    log_info "启动服务..."
    "${DC[@]}" up -d
    log_success "容器已启动，等待服务就绪..."
    sleep 10

    # 逐一健康检查（端口读 .env.cpu）
    local api_port
    local worker_port
    local frontend_port
    local rustfs_port
    api_port=$(get_env_key API_PORT)
    api_port="${api_port:-8000}"
    worker_port=$(get_env_key WORKER_PORT)
    worker_port="${worker_port:-8001}"
    frontend_port=$(get_env_key FRONTEND_PORT)
    frontend_port="${frontend_port:-80}"
    rustfs_port=$(get_env_key RUSTFS_PORT)
    rustfs_port="${rustfs_port:-9000}"

    if curl -fsS "http://localhost:${api_port}/api/v1/health" > /dev/null 2>&1; then
        log_success "Backend API 健康（:${api_port}）"
    else
        log_warning "Backend API 暂未响应（首次加载模型较慢，可稍后重试）"
    fi
    if curl -fsS "http://localhost:${worker_port}/health" > /dev/null 2>&1; then
        log_success "Worker 健康（:${worker_port}）"
    else
        log_warning "Worker 暂未响应（:${worker_port}）"
    fi
    if curl -fsS "http://localhost:${frontend_port}/" > /dev/null 2>&1; then
        log_success "前端健康（:${frontend_port}）"
    else
        log_warning "前端暂未响应（:${frontend_port}）"
    fi
    if curl -fsS "http://localhost:${rustfs_port}/health" > /dev/null 2>&1; then
        log_success "RustFS 健康（:${rustfs_port}）"
    else
        log_warning "RustFS 暂未响应（:${rustfs_port}）"
    fi

    echo ""
    log_success "=========================================="
    log_success " CPU 开发环境已启动"
    log_success "=========================================="
    echo ""
    echo "  Web UI:        http://localhost:${frontend_port}"
    echo "  API 文档:      http://localhost:${api_port}/docs"
    echo "  RustFS（回环）: http://127.0.0.1:${rustfs_port}"
    echo ""
    echo "  查看日志: ${DC[*]} logs -f"
    echo "  停止服务: ${DC[*]} down"
    echo ""
    log_warning "管理员账号: $(get_env_key TIANSHU_ADMIN_USERNAME)（初始密码见 ${ENV_FILE} 中 TIANSHU_ADMIN_PASSWORD，请妥善保存）"
    log_warning "CPU 模式比 GPU 慢 10-20 倍，仅适合开发调试"
    echo ""
}

# ----------------------------------------------------------------------------
# 模式：offline-build（联网机构建离线包）
# ----------------------------------------------------------------------------
build_offline() {
    MODE="offline-build"
    local platform="${PLATFORM:-amd64}"
    local output_dir="./docker-images"
    local models_dir="./models-offline"

    log_info "离线镜像包构建（平台: linux/${platform}，输出: ${output_dir}）"

    if [ "$DRY_RUN" -eq 1 ]; then
        log_info "将执行的操作:"
        echo "    1. 检查 Docker / NVIDIA 环境"
        echo "    2. 检查 ${models_dir}，缺失则运行 python3 backend/download_models.py --output ${models_dir}"
        echo "    3. buildx 构建 tianshu-backend:latest（backend/Dockerfile.offline，linux/${platform}）"
        echo "    4. buildx 构建 tianshu-frontend:latest（frontend/Dockerfile，linux/${platform}）"
        echo "    5. 拉取 rustfs/rustfs:latest（linux/${platform}）"
        echo "    6. docker save | gzip 导出三个镜像到 ${output_dir}/*-${platform}.tar.gz"
        echo "    7. 打包模型: tar czf ${output_dir}/models-offline.tar.gz ${models_dir}/"
        echo "    8. 复制 docker-compose.offline.yml / .env.example / mcp_config.example.json / setup.sh 到 ${output_dir}"
        log_warning "dry-run 模式：未执行任何构建"
        return 0
    fi

    if ! command -v docker > /dev/null 2>&1; then
        log_error "未安装 Docker"
        exit 1
    fi
    detect_compose
    log_success "Docker: $(docker --version)"

    if command -v nvidia-smi > /dev/null 2>&1 && nvidia-smi > /dev/null 2>&1; then
        log_success "NVIDIA 驱动: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2> /dev/null | head -1)"
    else
        log_warning "本机未检测到 NVIDIA GPU（仅构建镜像，不影响在 GPU 服务器上部署）"
    fi

    # 模型检查 / 下载
    if [ ! -d "$models_dir" ] || [ -z "$(ls -A "$models_dir" 2> /dev/null)" ]; then
        log_warning "模型目录缺失或为空，开始下载..."
        if ! command -v python3 > /dev/null 2>&1; then
            log_error "未安装 Python 3，无法下载模型"
            exit 1
        fi
        python3 -m pip install --quiet huggingface-hub modelscope loguru 2> /dev/null || true
        if python3 backend/download_models.py --output "$models_dir"; then
            log_success "模型下载完成"
        else
            log_error "模型下载失败，请手动执行: python3 backend/download_models.py --output $models_dir"
            exit 1
        fi
    else
        log_success "模型目录已存在: $models_dir（重新下载请加 --force 手动执行 download_models.py）"
    fi

    # 构建镜像
    log_info "构建后端镜像（backend/Dockerfile.offline，约 60-90 分钟）..."
    DOCKER_BUILDKIT=1 docker buildx build \
        --platform "linux/${platform}" \
        --file backend/Dockerfile.offline \
        --build-arg APT_MIRROR="$APT_MIRROR" \
        --build-arg PIP_MIRROR="$PIP_MIRROR" \
        --tag tianshu-backend:latest \
        --load \
        .
    log_success "后端镜像构建完成"

    log_info "构建前端镜像..."
    DOCKER_BUILDKIT=1 docker buildx build \
        --platform "linux/${platform}" \
        --file frontend/Dockerfile \
        --build-arg NPM_REGISTRY="$NPM_REGISTRY" \
        --tag tianshu-frontend:latest \
        --load \
        .
    log_success "前端镜像构建完成"

    log_info "拉取 RustFS 镜像（linux/${platform}）..."
    docker pull --platform "linux/${platform}" rustfs/rustfs:latest
    log_success "RustFS 镜像就绪"

    # 导出镜像
    log_info "导出镜像（约 10-20 分钟）..."
    mkdir -p "$output_dir"

    docker save tianshu-backend:latest | gzip > "${output_dir}/tianshu-backend-${platform}.tar.gz" &
    local pid_backend=$!
    docker save tianshu-frontend:latest | gzip > "${output_dir}/tianshu-frontend-${platform}.tar.gz" &
    local pid_frontend=$!
    docker save rustfs/rustfs:latest | gzip > "${output_dir}/rustfs-${platform}.tar.gz" &
    local pid_rustfs=$!
    wait "$pid_backend"
    wait "$pid_frontend"
    wait "$pid_rustfs"
    log_success "镜像导出完成"

    # 打包模型
    if [ -d "$models_dir" ] && [ ! -f "${output_dir}/models-offline.tar.gz" ]; then
        log_info "打包模型..."
        tar czf "${output_dir}/models-offline.tar.gz" "${models_dir}/"
        log_success "模型打包完成"
    else
        log_warning "模型目录不存在或已打包，跳过"
    fi

    # 复制配置文件
    log_info "复制配置文件..."
    cp docker-compose.offline.yml "${output_dir}/docker-compose.yml"
    cp docker-compose.offline.yml "${output_dir}/docker-compose.offline.yml"
    cp .env.example "${output_dir}/" 2> /dev/null || log_warning ".env.example 未找到，跳过"
    [ -f mcp_config.example.json ] && cp mcp_config.example.json "${output_dir}/"
    # 把本脚本一并打包，生产机直接 bash setup.sh --mode offline-deploy
    cp "$0" "${output_dir}/setup.sh"
    chmod +x "${output_dir}/setup.sh" 2> /dev/null || true
    log_success "配置文件复制完成"

    echo ""
    log_success "=========================================="
    log_success " 离线包构建完成: ${output_dir}"
    log_success "=========================================="
    ls -lh "$output_dir/"
    echo ""
    log_info "总大小: $(du -sh "$output_dir" | cut -f1)"
    echo ""
    log_info "下一步（传输到生产机并部署）:"
    echo "  rsync -avz --progress ${output_dir}/ user@server:/opt/tianshu/"
    echo "  ssh user@server 'cd /opt/tianshu && bash setup.sh --mode offline-deploy'"
    echo ""
}

# ----------------------------------------------------------------------------
# 模式：offline-deploy（生产机部署离线包）
# ----------------------------------------------------------------------------
deploy_offline() {
    MODE="offline-deploy"

    # 离线包内 docker-compose.yml 即 docker-compose.offline.yml 的副本
    local compose_file=""
    if [ -f docker-compose.offline.yml ]; then
        compose_file="docker-compose.offline.yml"
    elif [ -f docker-compose.yml ]; then
        compose_file="docker-compose.yml"
    else
        log_error "未找到 docker-compose.offline.yml / docker-compose.yml"
        log_error "请在离线包目录（含镜像 tar 包）中运行本脚本"
        exit 1
    fi

    log_info "离线部署（compose 文件: ${compose_file}）"

    # NVIDIA 强制检查（dry-run 放宽为告警）
    if ! command -v nvidia-smi > /dev/null 2>&1 || ! nvidia-smi > /dev/null 2>&1; then
        if [ "$DRY_RUN" -eq 1 ]; then
            log_warning "dry-run：未检测到 NVIDIA GPU（正式执行时将直接报错退出）"
        else
            log_error "未检测到可用的 NVIDIA 驱动，离线 GPU 部署无法继续"
            exit 1
        fi
    else
        log_success "NVIDIA 驱动正常"
        nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader || true
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        log_info "将执行的操作:"
        echo "    1. 检查 NVIDIA Container Toolkit"
        echo "    2. 检查 tianshu-backend-amd64.tar.gz / tianshu-frontend-amd64.tar.gz / rustfs-amd64.tar.gz / models-offline.tar.gz"
        echo "    3. docker load 加载三个镜像，tar xzf 解压模型"
        echo "    4. 生成 .env（JWT 自动生成、RUSTFS_PUBLIC_URL 按本机 IP 改写、显存/内存自动调谐）"
        echo "    5. docker compose -f ${compose_file} up -d（.env 启用 Redis 时附加 --profile redis）"
        echo "    6. 健康检查（端口读 .env 的 API_PORT / FRONTEND_PORT）+ 容器内 nvidia-smi 验证"
        log_warning "dry-run 模式：未执行任何部署操作"
        return 0
    fi

    detect_compose
    if docker run --rm --gpus all nvidia/cuda:12.6.2-base-ubuntu22.04 nvidia-smi > /dev/null 2>&1; then
        log_success "NVIDIA Container Toolkit 工作正常"
    else
        log_error "Docker 无法访问 GPU（NVIDIA Container Toolkit 缺失或配置错误）"
        log_error "安装指南: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
        exit 1
    fi

    # 检查离线包文件
    local missing=0
    local f
    for f in tianshu-backend-amd64.tar.gz tianshu-frontend-amd64.tar.gz rustfs-amd64.tar.gz models-offline.tar.gz; do
        if [ ! -f "$f" ] && [ ! -L "$f" ]; then
            log_error "缺少文件: $f"
            missing=1
        fi
    done
    if [ "$missing" -eq 1 ]; then
        log_error "请确认离线包全部文件已传输到当前目录"
        exit 1
    fi
    log_success "离线包文件齐全"

    # 加载镜像
    log_info "加载 Docker 镜像（约 5-10 分钟）..."
    docker load < tianshu-backend-amd64.tar.gz
    docker load < tianshu-frontend-amd64.tar.gz
    docker load < rustfs-amd64.tar.gz
    log_success "镜像加载完成"

    # 解压模型
    log_info "解压模型（约 5-10 分钟）..."
    tar xzf models-offline.tar.gz
    log_success "模型解压完成"

    create_directories

    # 生成配置并调谐（GPU 机器，tune_env 全量生效）
    prepare_env
    tune_env

    DC+=(-f "$compose_file")
    add_redis_profile

    log_info "启动服务..."
    "${DC[@]}" up -d
    log_success "容器已启动"

    # 健康检查（端口读 .env）
    verify_deployment || log_warning "健康检查存在告警，请查看上方信息"

    # 容器内 GPU 验证
    sleep 5
    if "${DC[@]}" exec -T worker nvidia-smi > /dev/null 2>&1; then
        log_success "Worker 容器可正常访问 GPU"
    else
        log_warning "无法在 Worker 容器内验证 GPU（可能仍在初始化）"
    fi

    show_info
}

# ----------------------------------------------------------------------------
# 模式：dev（开发模式，热重载）
# ----------------------------------------------------------------------------
deploy_dev() {
    MODE="dev"

    log_info "开发模式（docker-compose.dev.yml，热重载 + debugpy:5678）"

    if [ "$DRY_RUN" -eq 0 ]; then
        if ! command -v docker > /dev/null 2>&1; then
            log_error "未安装 Docker"
            exit 1
        fi
    fi
    detect_compose
    DC+=(-f docker-compose.dev.yml)

    prepare_env
    ensure_jwt_secret
    ensure_admin_password

    if [ "$DRY_RUN" -eq 1 ]; then
        log_info "将创建目录: models input output data/{uploads,output,db} logs/{backend,worker,mcp,scheduler}"
        log_info "将启动服务: ${DC[*]} up -d"
        log_warning "dry-run 模式：未执行构建与启动"
        return 0
    fi

    create_directories

    log_info "启动开发环境..."
    "${DC[@]}" up -d
    log_success "开发环境已启动"
    echo ""
    echo "  Backend (热重载): http://localhost:8000/docs"
    echo "  debugpy 调试端口: 5678"
    echo "  查看日志: ${DC[*]} logs -f"
    echo "  停止服务: ${DC[*]} down"
    echo ""
}

# ----------------------------------------------------------------------------
# 模式：native（本机原生运行，不用 Docker；Apple Silicon 自动启用 MPS 加速）
# ----------------------------------------------------------------------------
deploy_native() {
    MODE="native"

    local os_type arch
    os_type=$(uname -s)
    arch=$(uname -m)
    local is_mac_arm=0
    if [ "$os_type" = "Darwin" ] && [ "$arch" = "arm64" ]; then
        is_mac_arm=1
    fi

    log_info "原生部署模式（不依赖 Docker）"
    if [ "$is_mac_arm" -eq 1 ]; then
        log_info "检测到 Apple Silicon，MinerU 将自动使用 MPS 加速，VLM 走 MLX"
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        log_info "将执行的操作:"
        echo "    1. 检查 Python 3.10~3.12、ffmpeg（音视频解析需要）"
        echo "    2. 创建 .venv 虚拟环境并安装 backend/requirements.txt"
        echo "    3. 交互选择是否下载 VLM 模型，下载模型到 ./models"
        echo "    4. 生成 ~/mineru.json（指向本机 ./models 绝对路径）"
        echo "    5. 生成 backend/.env（若不存在）"
        echo "    6. 前台启动: .venv/bin/python backend/start_all.py --output-dir ./output"
        log_warning "dry-run 模式：未执行任何操作"
        return 0
    fi

    # --- 1. 环境检查 ---
    local py=""
    local cand ver
    for cand in python3.12 python3.11 python3.10 python3; do
        if command -v "$cand" > /dev/null 2>&1; then
            ver=$("$cand" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2> /dev/null || true)
            case "$ver" in
                3.10 | 3.11 | 3.12)
                    py="$cand"
                    break
                    ;;
            esac
        fi
    done
    if [ -z "$py" ]; then
        log_error "未找到 Python 3.10~3.12（MinerU 依赖的 ray 不支持 Python 3.13+）"
        [ "$os_type" = "Darwin" ] && log_info "可执行: brew install python@3.12"
        exit 1
    fi
    log_success "Python: $("$py" --version 2>&1)"

    if ! command -v ffmpeg > /dev/null 2>&1; then
        log_warning "未检测到 ffmpeg（仅音视频解析需要，可稍后安装）"
        [ "$os_type" = "Darwin" ] && log_info "可执行: brew install ffmpeg"
    fi

    # --- 2. 虚拟环境与依赖 ---
    if [ ! -x ".venv/bin/python" ]; then
        log_info "创建虚拟环境 .venv ..."
        "$py" -m venv .venv || {
            log_error "创建 .venv 失败"
            exit 1
        }
    fi
    log_info "安装后端依赖（首次约 10-20 分钟）..."
    .venv/bin/pip install --upgrade pip -i "$PIP_MIRROR"
    if ! .venv/bin/pip install -r backend/requirements.txt -i "$PIP_MIRROR"; then
        log_error "依赖安装失败"
        exit 1
    fi
    log_success "依赖安装完成"

    # --- 3. 模型下载 ---
    local models="mineru_pipeline,sensevoice"
    if ask_yn "是否下载 VLM 模型 MinerU2.5-Pro（vlm/hybrid 后端需要，约 3GB）" "Y"; then
        models="mineru_pipeline,mineru_vlm,sensevoice"
    fi
    log_info "下载模型到 ./models ..."
    if ! .venv/bin/python backend/download_models.py --output ./models --models "$models"; then
        log_warning "模型下载不完整，可稍后重试: .venv/bin/python backend/download_models.py --output ./models"
    fi

    # --- 4. mineru.json（本机绝对路径，容器路径版本不适用于原生运行） ---
    local root
    root=$(pwd)
    cat > "$HOME/mineru.json" << EOF
{
    "models-dir": {
        "pipeline": "${root}/models/PDF-Extract-Kit-1.0/models",
        "vlm": "${root}/models/MinerU2.5-Pro-2605-1.2B"
    },
    "config_version": "1.3.1"
}
EOF
    log_success "已生成 ~/mineru.json"

    # --- 5. backend/.env ---
    if [ ! -f "backend/.env" ]; then
        cp backend/.env.example backend/.env
        # 本地运行也生成随机 JWT 密钥，避免使用示例占位符
        local jwt
        jwt=$(openssl rand -hex 32 2> /dev/null || cat /dev/urandom | LC_ALL=C tr -dc 'a-f0-9' | head -c 64)
        if [ -n "$jwt" ]; then
            sed_i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${jwt}|" backend/.env
        fi
        log_success "已生成 backend/.env（JWT 密钥已随机化）"
    fi

    create_directories

    # --- 6. 前台启动（Ctrl+C 停止全部服务） ---
    echo ""
    log_success "准备就绪，即将前台启动后端服务（API + Worker + Scheduler）"
    echo ""
    echo "  API 文档:  http://localhost:8000/docs"
    echo "  前端界面:  cd frontend && npm install && npm run dev"
    echo "  停止服务:  Ctrl+C"
    echo ""
    exec .venv/bin/python backend/start_all.py --output-dir ./output
}

# ----------------------------------------------------------------------------
# 交互式模式菜单
# ----------------------------------------------------------------------------
choose_mode() {
    echo ""
    echo "╔════════════════════════════════════════╗"
    echo "║   Tianshu (天枢) 一键部署              ║"
    echo "╚════════════════════════════════════════╝"
    echo ""
    echo "请选择部署模式:"
    echo "  1) GPU 标准部署（全引擎，docker-compose.yml）"
    echo "  2) 纯 pipeline 部署（省 4GB 模型，自动调谐并发/显存）"
    echo "  3) CPU 本地开发（Mac Apple Silicon）"
    echo "  4) 离线构建（联网机：构建离线镜像包）"
    echo "  5) 离线部署（生产机：部署离线镜像包）"
    echo "  6) 开发模式（热重载 + debugpy）"
    echo "  7) 原生部署（不用 Docker，Mac Apple Silicon 自动 MPS 加速）"
    echo "  0) 退出"
    echo ""

    local choice=""
    while true; do
        printf "${BLUE}[?]${NC} 请输入选项 [0-7]: "
        read -r choice
        case "$choice" in
            1) MODE="gpu"; break ;;
            2) MODE="pipeline"; break ;;
            3) MODE="cpu"; break ;;
            4) MODE="offline-build"; break ;;
            5) MODE="offline-deploy"; break ;;
            6) MODE="dev"; break ;;
            7) MODE="native"; break ;;
            0) log_info "已退出"; exit 0 ;;
            *) log_error "无效选项，请重新输入" ;;
        esac
    done
}

# ----------------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------------
main() {
    trap 'log_warning "操作被用户中断"; exit 130' INT TERM

    if [ -z "$MODE" ]; then
        if [ "$INTERACTIVE" -eq 1 ]; then
            choose_mode
        else
            log_error "非交互环境必须通过 --mode 指定部署模式"
            usage
            exit 1
        fi
    fi

    case "$MODE" in
        gpu | pipeline | cpu | offline-build | dev | native) choose_network ;;
    esac

    case "$MODE" in
        gpu) deploy_gpu_mode gpu ;;
        pipeline) deploy_gpu_mode pipeline ;;
        cpu) deploy_cpu ;;
        offline-build) build_offline ;;
        offline-deploy) deploy_offline ;;
        dev) deploy_dev ;;
        native) deploy_native ;;
        *)
            log_error "未知模式: ${MODE}（可选: gpu / pipeline / cpu / offline-build / offline-deploy / dev / native）"
            exit 1
            ;;
    esac
}

main
