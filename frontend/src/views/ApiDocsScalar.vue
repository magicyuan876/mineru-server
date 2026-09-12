<template>
  <!-- 完全使用 Scalar 自身样式，不添加额外包装 -->
  <div class="scalar-container">
    <!-- 加载状态 -->
    <div v-if="isLoading" class="loading-state">
      <div class="loading-content">
        <div class="loading-spinner"></div>
        <p>{{ t('apiDocs.loading') }}</p>
      </div>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="loadError" class="error-state">
      <div class="error-content">
        <svg class="error-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <h3>{{ t('apiDocs.loadError') }}</h3>
        <p>{{ loadError }}</p>
        <button @click="retryLoad" class="retry-button">{{ t('apiDocs.retry') }}</button>
      </div>
    </div>

    <!-- Scalar API Reference - 完全独立渲染 -->
    <ApiReference
      v-else
      :configuration="scalarConfig"
      @ready="onScalarReady"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ApiReference } from '@scalar/api-reference'
import { useAuthStore } from '@/stores'
import { useI18n } from 'vue-i18n'

// 导入 Scalar 样式 - 但会在页面底部添加样式覆盖来保护我们的样式
import '@scalar/api-reference/style.css'

const authStore = useAuthStore()
const { locale, t } = useI18n()

// 响应式配置
const isLoading = ref(true)
const loadError = ref('')
const openApiSpec = ref<any>(null)

// API 文档翻译字典（中文 -> 英文）
const apiTranslations: Record<string, string> = {
  // 标签/分类
  '系统信息': 'System Info',
  '任务管理': 'Task Management',
  '队列管理': 'Queue Management',
  '系统管理': 'System Management',
  '文件服务': 'File Service',
  'Authentication': 'Authentication',

  // 通用描述
  'API根路径': 'API Root',
  '健康检查接口': 'Health Check',
  '列出所有可用的处理引擎': 'List All Available Processing Engines',
  '需要认证。返回系统中所有可用的处理引擎信息。': 'Requires authentication. Returns information about all available processing engines in the system.',

  // 任务管理
  '提交文档解析任务': 'Submit Document Parsing Task',
  '需要认证和 TASK_SUBMIT 权限。': 'Requires authentication and TASK_SUBMIT permission.',
  '立即返回 task_id，任务在后台异步处理。': 'Returns task_id immediately, task is processed asynchronously in the background.',

  '查询任务状态和详情': 'Query Task Status and Details',
  '需要认证。用户只能查看自己的任务，管理员可以查看所有任务。': 'Requires authentication. Users can only view their own tasks, administrators can view all tasks.',
  '当任务完成时，会自动返回解析后的内容（data 字段）': 'When the task is completed, the parsed content will be automatically returned (data field)',

  '取消任务：仅对 pending / processing / paused 状态的任务生效': 'Cancel Task (only effective for tasks in pending/processing/paused status)',
  '需要认证。用户只能取消自己的任务，管理员可以取消任何任务。': 'Requires authentication. Users can only cancel their own tasks, administrators can cancel any task.',

  // 队列管理
  '获取队列统计信息': 'Get Queue Statistics',
  '需要认证和 QUEUE_VIEW 权限。': 'Requires authentication and QUEUE_VIEW permission.',

  '获取任务列表': 'Get Task List',
  '需要认证。普通用户只能看到自己的任务，管理员/经理可以看到所有任务。': 'Requires authentication. Regular users can only see their own tasks, administrators/managers can see all tasks.',

  // 系统管理
  '清理旧任务（管理接口）': 'Clean Up Old Tasks (Admin)',
  '同时删除任务的结果文件和数据库记录。': 'Deletes both task result files and database records.',
  '需要管理员权限。': 'Requires administrator permission.',

  '重置超时的 processing 任务（管理接口）': 'Reset Stale Processing Tasks (Admin)',

  // 文件服务
  '提供输出文件的访问服务': 'Serve Output Files',
  '支持 URL 编码的中文路径': 'Supports URL-encoded Chinese paths',
  '注意：Nginx 代理会去掉 /api/ 前缀，所以这里不需要 /api/': 'Note: Nginx proxy removes /api/ prefix, so /api/ is not needed here',

  // 认证相关
  '用户注册': 'User Registration',
  '创建新用户账户。默认角色为 \'user\'，需要管理员才能创建其他角色。': 'Create a new user account. Default role is \'user\', administrator permission required to create other roles.',

  '用户登录': 'User Login',
  '使用用户名和密码登录，返回 JWT Access Token。': 'Login with username and password, returns JWT Access Token.',

  '获取当前登录用户信息': 'Get Current User Info',
  '需要认证。返回当前用户的详细信息。': 'Requires authentication. Returns detailed information about the current user.',

  '更新当前用户信息': 'Update Current User Info',
  '用户可以更新自己的邮箱和全名，不能更新角色。': 'Users can update their own email and full name, but cannot update their role.',

  '创建 API Key': 'Create API Key',
  '为当前用户创建一个新的 API Key。API Key 只会在创建时返回一次，请妥善保管。': 'Create a new API Key for the current user. API Key is only returned once during creation, please keep it safe.',

  '列出当前用户的所有 API Key': 'List All API Keys for Current User',
  '返回 API Key 列表，不包含完整的 key，只显示前缀。': 'Returns API Key list, does not include full key, only shows prefix.',

  '删除 API Key': 'Delete API Key',
  '删除指定的 API Key。只能删除自己的 API Key。': 'Delete the specified API Key. Can only delete your own API Keys.',

  '列出所有用户': 'List All Users',
  '需要管理员权限。返回用户列表。': 'Requires administrator permission. Returns user list.',

  '创建用户 (管理员)': 'Create User (Admin)',
  '管理员可以创建任意角色的用户。': 'Administrators can create users with any role.',

  '更新用户信息 (管理员)': 'Update User Info (Admin)',
  '管理员可以更新任意用户的信息，包括角色和状态。': 'Administrators can update any user\'s information, including role and status.',

  '删除用户 (管理员)': 'Delete User (Admin)',
  '管理员可以删除用户。不能删除自己。': 'Administrators can delete users. Cannot delete yourself.',

  '检查 SSO 是否启用': 'Check if SSO is Enabled',
  '返回 SSO 配置状态。': 'Returns SSO configuration status.',

  'SSO 登录入口': 'SSO Login Entry',
  '重定向到 SSO 提供者进行认证。': 'Redirects to SSO provider for authentication.',

  'SSO 回调接口': 'SSO Callback',
  '处理 SSO 提供者的回调，创建或获取用户，返回 JWT Token。': 'Handles SSO provider callback, creates or retrieves user, returns JWT Token.',

  // 参数描述
  '文件: PDF/图片/Office/HTML/音频/视频等多种格式': 'File: PDF/Image/Office/HTML/Audio/Video and other formats',
  '处理后端: pipeline, hybrid-auto-engine, vlm-auto-engine, hybrid-http-client, vlm-http-client, sensevoice, video, etc.': 'Processing backend: pipeline, hybrid-auto-engine, vlm-auto-engine, hybrid-http-client, vlm-http-client, sensevoice, video, etc.',
  '语言: auto/ch/en/korean/japan等': 'Language: auto/ch/en/korean/japan etc.',
  '解析方法: auto/txt/ocr': 'Parsing method: auto/txt/ocr',
  '是否启用公式识别': 'Enable formula recognition',
  '是否启用表格识别': 'Enable table recognition',
  '优先级，数字越大越优先': 'Priority, higher number means higher priority',
  '视频处理时是否保留提取的音频文件': 'Whether to keep extracted audio files during video processing',
  '是否启用视频关键帧OCR识别（实验性功能）': 'Enable video keyframe OCR recognition (experimental feature)',
  '关键帧OCR引擎: mineru': 'Keyframe OCR engine: mineru',
  '是否保留提取的关键帧图像': 'Whether to keep extracted keyframe images',
  '是否启用水印去除（支持 PDF/图片）': 'Enable watermark removal (supports PDF/images)',
  '水印检测置信度阈值（0.0-1.0，推荐 0.35）': 'Watermark detection confidence threshold (0.0-1.0, recommended 0.35)',
  '水印掩码膨胀大小（像素，推荐 10）': 'Watermark mask dilation size (pixels, recommended 10)',

  '是否上传图片到MinIO并替换链接（仅当任务完成时有效）': 'Whether to upload images to MinIO and replace links (only valid when task is completed)',
  '返回格式: markdown(默认)/json/both': 'Return format: markdown(default)/json/both',

  '筛选状态: pending/processing/completed/failed': 'Filter status: pending/processing/completed/failed',
  '返回数量限制': 'Return quantity limit',

  '清理N天前的任务': 'Clean up tasks older than N days',
  '超时时间（分钟）': 'Timeout (minutes)',

  // 应用描述
  '天枢 - 企业级 AI 数据预处理平台 | 支持文档、图片、音频、视频等多模态数据处理 | 企业级认证授权': 'Tianshu - Enterprise AI Data Preprocessing Platform | Supports multimodal data processing including documents, images, audio, video | Enterprise-grade authentication and authorization',
  '直接访问后端（推荐用于 API 测试）': 'Direct backend access (recommended for API testing)',
}

// 翻译函数
function translateText(text: string, lang: string): string {
  if (lang === 'zh-CN' || !text) {
    return text
  }
  return apiTranslations[text] || text
}

// 递归翻译 OpenAPI schema
function translateOpenApiSpec(spec: any, lang: string): any {
  if (!spec || lang === 'zh-CN') {
    return spec
  }

  const translated = JSON.parse(JSON.stringify(spec))

  // 翻译基本信息
  if (translated.info) {
    if (translated.info.title) {
      translated.info.title = translateText(translated.info.title, lang)
    }
    if (translated.info.description) {
      translated.info.description = translateText(translated.info.description, lang)
    }
  }

  // 翻译服务器描述
  if (translated.servers) {
    translated.servers = translated.servers.map((server: any) => ({
      ...server,
      description: translateText(server.description, lang),
    }))
  }

  // 翻译标签
  if (translated.tags) {
    translated.tags = translated.tags.map((tag: any) => ({
      ...tag,
      name: translateText(tag.name, lang),
      description: tag.description ? translateText(tag.description, lang) : undefined,
    }))
  }

  // 翻译路径
  if (translated.paths) {
    Object.keys(translated.paths).forEach(path => {
      const pathItem = translated.paths[path]
      Object.keys(pathItem).forEach(method => {
        if (typeof pathItem[method] === 'object') {
          const operation = pathItem[method]

          // 翻译 summary 和 description
          if (operation.summary) {
            operation.summary = translateText(operation.summary, lang)
          }
          if (operation.description) {
            operation.description = translateText(operation.description, lang)
          }

          // 翻译标签
          if (operation.tags) {
            operation.tags = operation.tags.map((tag: string) => translateText(tag, lang))
          }

          // 翻译参数
          if (operation.parameters) {
            operation.parameters = operation.parameters.map((param: any) => ({
              ...param,
              description: param.description ? translateText(param.description, lang) : undefined,
            }))
          }

          // 翻译请求体
          if (operation.requestBody?.content) {
            Object.keys(operation.requestBody.content).forEach(contentType => {
              const content = operation.requestBody.content[contentType]
              if (content.schema?.properties) {
                Object.keys(content.schema.properties).forEach(propName => {
                  const prop = content.schema.properties[propName]
                  if (prop.description) {
                    prop.description = translateText(prop.description, lang)
                  }
                })
              }
            })
          }
        }
      })
    })
  }

  return translated
}

// 加载并翻译 OpenAPI 规范
async function loadOpenApiSpec() {
  try {
    const response = await fetch(`${window.location.origin}/api/openapi.json`)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }
    const spec = await response.json()
    openApiSpec.value = translateOpenApiSpec(spec, locale.value)
    isLoading.value = false
  } catch (error: any) {
    loadError.value = `无法访问 OpenAPI 文档: ${error.message}`
    isLoading.value = false
    console.error('OpenAPI 文档加载失败:', error)
  }
}

// 监听语言变化，重新翻译
watch(locale, async () => {
  if (openApiSpec.value) {
    // 重新加载并翻译
    await loadOpenApiSpec()
  }
})

// Scalar 配置（响应式）
const scalarConfig = computed(() => ({
  // OpenAPI 规范（使用翻译后的版本）
  spec: {
    content: openApiSpec.value,
  },

  // 主题配置 - 使用 Scalar 默认主题
  theme: 'default',

  // 布局配置 - 使用现代布局
  layout: 'modern' as 'modern',

  // 显示配置
  showSidebar: true,
  darkMode: false,

  // 隐藏不需要的元素
  hiddenClients: [], // 可以隐藏特定语言的客户端示例

  // 默认 HTTP 客户端
  defaultHttpClient: {
    targetKey: 'javascript',
    clientKey: 'fetch',
  },

  // 认证配置
  authentication: {
    preferredSecurityScheme: 'bearerAuth',
    http: {
      bearer: {
        token: authStore.token || '',
      },
    },
    apiKey: {
      token: authStore.token || '',
    },
  },

  // 服务器配置 - 提供前端代理和后端直连两种方式
  servers: [
    {
      url: window.location.origin + '/api',
      description: '通过前端代理访问（推荐）',
    },
    {
      url: `${window.location.protocol}//${window.location.hostname}:8000`,
      description: '直接访问后端（用于 API 测试）',
    },
  ],

  // 其他配置
  searchHotKey: 'k',
  withDefaultFonts: true,
}))

// Scalar 就绪回调
function onScalarReady() {
  console.log('✅ Scalar API Reference 已加载')
}

// 重试加载
function retryLoad() {
  isLoading.value = true
  loadError.value = ''
  loadOpenApiSpec()
}

// 组件挂载时初始化
onMounted(async () => {
  // 加载并翻译 OpenAPI 文档
  await loadOpenApiSpec()
})
</script>

<style scoped>
/* 最小化样式，让 Scalar 完全控制 */
.scalar-container {
  width: 100%;
  height: calc(100vh - 140px);
  position: relative;
  /* 隔离 Scalar 样式，防止污染全局 */
  isolation: isolate;
}

/* 加载状态样式 */
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.loading-content {
  text-align: center;
}

.loading-spinner {
  width: 48px;
  height: 48px;
  margin: 0 auto 16px;
  border: 2px solid #e5e7eb;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-content p {
  color: #6b7280;
  font-size: 14px;
}

/* 错误状态样式 */
.error-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.error-content {
  text-align: center;
  padding: 48px;
}

.error-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 16px;
  color: #ef4444;
}

.error-content h3 {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 8px;
}

.error-content p {
  color: #6b7280;
  margin-bottom: 16px;
}

.retry-button {
  padding: 8px 16px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: background 0.2s;
}

.retry-button:hover {
  background: #2563eb;
}
</style>

<style>
/* 全局样式保护：覆盖 Scalar 可能污染的样式 */
/* 使用高优先级选择器确保应用样式不被破坏 */

/* 保护 Tailwind 蓝色按钮 */
button.bg-blue-600,
a.bg-blue-600,
.bg-blue-600 {
  background-color: rgb(37 99 235) !important;
  color: white !important;
}

button.bg-blue-500,
a.bg-blue-500,
.bg-blue-500 {
  background-color: rgb(59 130 246) !important;
  color: white !important;
}

button.bg-blue-700,
a.bg-blue-700,
.bg-blue-700 {
  background-color: rgb(29 78 216) !important;
  color: white !important;
}

button.hover\:bg-blue-700:hover,
a.hover\:bg-blue-700:hover,
.hover\:bg-blue-700:hover {
  background-color: rgb(29 78 216) !important;
}

button.hover\:bg-blue-600:hover,
a.hover\:bg-blue-600:hover,
.hover\:bg-blue-600:hover {
  background-color: rgb(37 99 235) !important;
}

/* 保护 btn-primary 类 */
.btn-primary {
  background: linear-gradient(to right, rgb(37 99 235), rgb(29 78 216)) !important;
  color: white !important;
}

.btn-primary:hover {
  background: linear-gradient(to right, rgb(29 78 216), rgb(30 64 175)) !important;
}

/* 保护头像和其他圆形元素 */
.rounded-full {
  border-radius: 9999px !important;
}

/* 保护文本颜色 */
.text-white {
  color: white !important;
}

/* 保护背景渐变 */
.bg-gradient-to-r {
  background-image: linear-gradient(to right, var(--tw-gradient-stops)) !important;
}

.bg-gradient-to-br {
  background-image: linear-gradient(to bottom right, var(--tw-gradient-stops)) !important;
}

/* 保护 from-blue-* 和 to-blue-* 渐变颜色 */
.from-blue-500 {
  --tw-gradient-from: rgb(59 130 246) !important;
  --tw-gradient-to: rgb(59 130 246 / 0) !important;
  --tw-gradient-stops: var(--tw-gradient-from), var(--tw-gradient-to) !important;
}

.from-blue-600 {
  --tw-gradient-from: rgb(37 99 235) !important;
  --tw-gradient-to: rgb(37 99 235 / 0) !important;
  --tw-gradient-stops: var(--tw-gradient-from), var(--tw-gradient-to) !important;
}

.to-blue-500 {
  --tw-gradient-to: rgb(59 130 246) !important;
}

.to-blue-600 {
  --tw-gradient-to: rgb(37 99 235) !important;
}

.to-blue-700 {
  --tw-gradient-to: rgb(29 78 216) !important;
}

.to-blue-800 {
  --tw-gradient-to: rgb(30 64 175) !important;
}

/* 保护其他渐变颜色（用于角色标签） */
.from-red-500 {
  --tw-gradient-from: rgb(239 68 68) !important;
  --tw-gradient-to: rgb(239 68 68 / 0) !important;
  --tw-gradient-stops: var(--tw-gradient-from), var(--tw-gradient-to) !important;
}

.to-red-600 {
  --tw-gradient-to: rgb(220 38 38) !important;
}

.from-yellow-500 {
  --tw-gradient-from: rgb(234 179 8) !important;
  --tw-gradient-to: rgb(234 179 8 / 0) !important;
  --tw-gradient-stops: var(--tw-gradient-from), var(--tw-gradient-to) !important;
}

.to-yellow-600 {
  --tw-gradient-to: rgb(202 138 4) !important;
}
</style>
