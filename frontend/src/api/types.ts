/**
 * API 类型定义
 */

// ==================== 认证相关类型 ====================

// 用户角色
export type UserRole = 'admin' | 'manager' | 'user'

// 用户信息
export interface User {
  user_id: string
  username: string
  email: string
  full_name?: string
  role: UserRole
  is_active: boolean
  is_sso: boolean
  sso_provider?: string
  created_at: string
  last_login?: string
}

// 登录请求
export interface LoginRequest {
  username: string
  password: string
}

// 登录响应
export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
}

// 注册请求
export interface RegisterRequest {
  username: string
  email: string
  password: string
  full_name?: string
  role?: UserRole
  invite_code?: string
}

// 修改密码请求
export interface PasswordChangeRequest {
  old_password: string
  new_password: string
}

// API Key 创建请求
export interface APIKeyCreate {
  name: string
  expires_days?: number
}

// API Key 响应
export interface APIKeyResponse {
  key_id: string
  api_key: string
  prefix: string
  name: string
  created_at: string
  expires_at?: string
}

// API Key 信息 (列表项)
export interface APIKeyInfo {
  key_id: string
  name: string
  prefix: string
  is_active: boolean
  created_at: string
  expires_at?: string
  last_used?: string
}

// API Key 列表响应
export interface APIKeyListResponse {
  success: boolean
  count: number
  api_keys: APIKeyInfo[]
}

// ==================== 任务相关类型 ====================

// 任务状态 (✅ 修复：添加 'paused' 状态)
export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'paused'

// 后端类型
export type Backend =
  | 'auto'              // 自动选择引擎
  | 'pipeline'          // MinerU Pipeline (传统多模型管道)
  | 'vlm-auto-engine'   // MinerU VLM 自动 (视觉大模型 - 本地)
  | 'hybrid-auto-engine'// MinerU 混合高精度 (本地)
  | 'vlm-http-client'   // [新增] MinerU VLM Client (远程)
  | 'hybrid-http-client'// [新增] MinerU Hybrid Client (远程)
  | 'sensevoice'
  | 'video'
  | 'fasta'             // FASTA 生物序列格式
  | 'genbank'           // GenBank 基因序列注释格式
  | 'vlm-transformers'  // (已废弃，保留兼容)
  | 'vlm-vllm-engine'   // (已废弃，保留兼容)

// 语言类型 (扩充以支持 MinerU 所有语言)
export type Language =
  | 'auto'
  | 'ch' | 'en' | 'korean' | 'japan'
  | 'chinese_cht' // 繁体中文
  | 'ch_server' | 'ch_lite'
  | 'th' // 泰语
  | 'vi' // 越南语
  | 'ru' // 俄语
  | 'ar' // 阿拉伯语
  | 'fr' // 法语
  | 'de' // 德语
  | 'ta' // 泰米尔语
  | 'te' // 泰卢固语
  | 'ka' // 卡纳达语
  | 'el' // 希腊语
  | 'latin' // 拉丁语系
  | 'cyrillic' // 西里尔语系
  | 'devanagari' // 梵文

// 解析方法
export type ParseMethod = 'auto' | 'txt' | 'ocr'

// 任务配置选项 (对应数据库存储的 JSON 结构)
export interface TaskOptions {
  lang: Language
  method: ParseMethod
  formula_enable: boolean
  table_enable: boolean
  priority?: number

  // 分页
  start_page?: number
  end_page?: number

  // 远程配置
  server_url?: string

  // 调试与输出控制
  draw_layout_bbox?: boolean
  draw_span_bbox?: boolean
  dump_markdown?: boolean
  dump_middle_json?: boolean
  dump_model_output?: boolean
  dump_content_list?: boolean
  dump_orig_pdf?: boolean

  // 旧字段兼容
  force_ocr?: boolean
  draw_layout?: boolean
  draw_span?: boolean
}

// 任务提交请求 (前端 Form 表单数据)
export interface SubmitTaskRequest {
  file: File
  backend?: Backend
  lang?: Language
  method?: ParseMethod
  formula_enable?: boolean
  table_enable?: boolean
  priority?: number

  // 页码范围
  start_page?: number
  end_page?: number

  // 远程服务地址 (Client 模式必填)
  server_url?: string

  // MinerU 详细调试参数
  draw_layout_bbox?: boolean // 是否绘制布局边框
  draw_span_bbox?: boolean   // 是否绘制文本Span边框
  dump_markdown?: boolean
  dump_middle_json?: boolean
  dump_model_output?: boolean
  dump_content_list?: boolean
  dump_orig_pdf?: boolean

  // 兼容旧字段 (即将废弃)
  draw_layout?: boolean
  draw_span?: boolean
  force_ocr?: boolean

  // Video 专属参数
  keep_audio?: boolean
  enable_keyframe_ocr?: boolean
  ocr_backend?: string
  keep_keyframes?: boolean

  // 水印去除参数
  remove_watermark?: boolean
  watermark_conf_threshold?: number
  watermark_dilation?: number

  // Audio 专属参数 (SenseVoice)
  enable_speaker_diarization?: boolean

  // Office 转换参数
}

// 任务信息
export interface Task {
  task_id: string
  file_name: string
  status: TaskStatus
  backend: Backend
  priority: number
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  worker_id: string | null
  retry_count: number
  result_path: string | null | 'CLEARED' // ✅ 修复：支持 'CLEARED' 状态标记
  source_url?: string | null
  is_parent?: boolean
  child_count?: number
  child_completed?: number
  subtask_progress?: {
    total: number
    completed: number
    percentage: number
  }
  // 子任务列表（父任务详情接口返回；chunk_info 为 PDF 分片页码范围或 zip 解包条目信息）
  subtasks?: Array<{
    task_id: string
    status: TaskStatus
    chunk_info?: {
      start_page?: number
      end_page?: number
      page_count?: number
      index?: number
      entry_name?: string
    } | null
    error_message?: string | null
  }>
  data?: {
    markdown_file: string
    content: string
    images_uploaded: boolean
    has_images: boolean | null
    json_file?: string
    json_content?: any
    json_available?: boolean
    pdf_path?: string
  } | null
}

// 任务提交响应
export interface SubmitTaskResponse {
  success: boolean
  task_id: string
  status: TaskStatus
  message: string
  file_name: string
  created_at: string
}

// 任务状态响应
export interface TaskStatusResponse extends Task {
  success: boolean
  message?: string
}

// 队列统计
export interface QueueStats {
  pending: number
  processing: number
  completed: number
  failed: number
  cancelled: number
}

// 队列统计响应
export interface QueueStatsResponse {
  success: boolean
  stats: QueueStats
  total: number
  timestamp: string
}

// 任务列表查询参数
export interface TaskQueryParams {
  page?: number
  page_size?: number
  status?: string
  backend?: string
  search?: string
}

// 任务列表响应
export interface TaskListResponse {
  success: boolean
  total: number
  page: number
  page_size: number
  count: number
  tasks: Task[]
  can_view_all?: boolean
}

// 通用响应
export interface ApiResponse<T = any> {
  success: boolean
  message?: string
  data?: T
}

// ==================== 引擎信息类型 ====================

export interface EngineItem {
  name: string
  display_name: string
  version?: string
  description?: string
  supported_formats: string[]
}

export interface EngineSystemInfo {
  platform: string
}

export interface EnginesResponse {
  success: boolean
  engines: {
    document: EngineItem[]
    audio: EngineItem[]
    video: EngineItem[]
    format: EngineItem[]
    office: EngineItem[]
  }
  system_info: EngineSystemInfo
  timestamp: string
}

// ==================== 系统配置类型 ====================

// 系统配置
export interface SystemConfig {
  system_name: string
  system_logo: string
  show_github_star: boolean
  allow_registration: boolean
  registration_invite_required?: boolean
  registration_invite_code?: string
}

// 系统配置响应
export interface SystemConfigResponse {
  success: boolean
  config: SystemConfig
}

// 系统配置更新请求
export interface SystemConfigUpdateRequest {
  system_name?: string
  system_logo?: string
  show_github_star?: boolean
  allow_registration?: boolean
  registration_invite_code?: string
  image_caption_enabled?: boolean
  image_caption_api_base?: string
  image_caption_api_key?: string
  image_caption_model?: string
  image_caption_prompt?: string
  image_caption_max_images?: number
  image_caption_concurrency?: number
  image_caption_timeout?: number
}

// 图片描述（多模态大模型）配置
export interface ImageCaptionConfig {
  enabled: boolean
  api_base: string
  api_key: string
  model: string
  prompt: string
  max_images: number
  concurrency: number
  timeout: number
}

// 图片描述配置响应
export interface ImageCaptionConfigResponse {
  success: boolean
  config: ImageCaptionConfig
}

// 图片描述连接测试结果
export interface ImageCaptionTestResult {
  success: boolean
  message: string
  latency_ms: number
}
