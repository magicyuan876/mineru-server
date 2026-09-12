# Tianshu (天枢) Frontend - Multi-stage Docker Build
# Vue 3 + TypeScript + Vite 企业级前端应用
#
# 构建方式:
#   docker build -t tianshu-frontend:latest -f frontend/Dockerfile .
#
# 运行方式:
#   docker run -p 80:80 tianshu-frontend:latest

# ============================================================================
# 镜像源配置（构建参数）：
#   - 默认使用 npmmirror 国内镜像
#   - 海外网络: docker buildx build --build-arg NPM_REGISTRY=https://registry.npmjs.org ...
# ============================================================================
ARG NPM_REGISTRY=https://registry.npmmirror.com

# ============================================================================
# Stage 1: Build Stage
# ============================================================================
FROM node:20-alpine AS builder
ARG NPM_REGISTRY

WORKDIR /app

# 复制 package.json 和 package-lock.json
COPY frontend/package*.json ./

# 安装依赖（NPM_REGISTRY 非空时使用指定 registry，默认 npmmirror 加速）
# 注意：构建阶段需要 devDependencies（包括 vite, typescript, postcss 等）
# 使用 npm ci 严格按 lock 文件安装，保证可重现
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi && \
    npm ci --ignore-scripts && \
    npm cache clean --force

# 复制前端源代码
COPY frontend/ ./

# 构建生产版本
RUN npm run build

# ============================================================================
# Stage 2: Production Stage with Nginx
# ============================================================================
FROM nginx:1.27-alpine AS production

# 安装 curl 用于健康检查
RUN apk add --no-cache curl

# 复制自定义 Nginx 配置
COPY <<'EOF' /etc/nginx/conf.d/default.conf
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # 文件上传大小限制（0 表示不限制）
    client_max_body_size ${NGINX_CLIENT_MAX_BODY_SIZE};

    # Gzip 压缩
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript
               application/x-javascript application/xml+rss
               application/javascript application/json;

    # 前端路由支持（Vue Router History Mode）
    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        # location 内一旦定义 add_header 就不会继承 server 级安全头，需在此重复
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-XSS-Protection "1; mode=block" always;
        add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: https: http:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' ws: wss:; font-src 'self' data:" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    }

    # 静态资源缓存（排除 /api/ 路径，避免干扰后端静态文件服务）
    location ~* ^(?!/api/).*\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # API 代理（包括静态文件）
    # /api/v1/files/output/* 会被代理到后端的静态文件服务
    #
    # ⚠️ proxy_pass 末尾不能加斜杠：加了斜杠 nginx 会把 location 匹配的 /api/ 前缀
    # 替换掉，后端收到的是 /v1/xxx，而 FastAPI 的路由挂在 /api/v1 前缀下 → 全部 404。
    # 前端生产构建的 VITE_API_BASE_URL=/api（frontend/.env.production），请求路径为
    # /api/v1/xxx，必须原样透传给后端。
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # RustFS 对象存储反代（解析结果图片）
    # RustFS 端口仅绑定宿主机回环，浏览器统一经此路径访问图片
    # ⚠️ proxy_pass 末尾带斜杠：/s3/<bucket>/<object> → /<bucket>/<object>
    location /s3/ {
        proxy_pass http://rustfs:9000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # WebSocket 支持
    location /ws/ {
        proxy_pass http://backend:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    # img-src 放行 https:/http: 因为 RustFS 图片可能配置为外部 URL
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: https: http:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' ws: wss:; font-src 'self' data:" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # 隐藏 Nginx 版本
    server_tokens off;
}
EOF

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 创建启动脚本（替换 Nginx 配置中的环境变量）
RUN cat > /docker-entrypoint.sh <<'SCRIPT'
#!/bin/sh
set -e

# 设置默认值（如果环境变量未设置，0 表示不限制）
export NGINX_CLIENT_MAX_BODY_SIZE=${NGINX_CLIENT_MAX_BODY_SIZE:-0}

# 替换 Nginx 配置中的环境变量
envsubst '${NGINX_CLIENT_MAX_BODY_SIZE}' < /etc/nginx/conf.d/default.conf > /tmp/default.conf
mv /tmp/default.conf /etc/nginx/conf.d/default.conf

# 启动 Nginx
exec nginx -g 'daemon off;'
SCRIPT

RUN chmod +x /docker-entrypoint.sh

# 暴露端口
EXPOSE 80

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost/ || exit 1

# 使用启动脚本
CMD ["/docker-entrypoint.sh"]
