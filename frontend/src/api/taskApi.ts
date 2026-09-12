/**
 * 任务相关 API
 */
import apiClient from './client'
import type {
  SubmitTaskRequest,
  SubmitTaskResponse,
  TaskStatusResponse,
  TaskListResponse,
  ApiResponse,
  TaskQueryParams,
} from './types'

// =================================================================
// 核心任务操作
// =================================================================

/**
 * 提交任务
 */
export async function submitTask(request: SubmitTaskRequest): Promise<SubmitTaskResponse> {
  const formData = new FormData()
  formData.append('file', request.file)

  // 基础参数
  if (request.backend) formData.append('backend', request.backend)
  if (request.lang) formData.append('lang', request.lang)
  if (request.method) formData.append('method', request.method)
  if (request.formula_enable !== undefined) formData.append('formula_enable', String(request.formula_enable))
  if (request.table_enable !== undefined) formData.append('table_enable', String(request.table_enable))
  if (request.priority !== undefined) formData.append('priority', String(request.priority))

  // 分页与模式
  if (request.start_page !== undefined) formData.append('start_page', String(request.start_page))
  if (request.end_page !== undefined) formData.append('end_page', String(request.end_page))
  if (request.force_ocr !== undefined) formData.append('force_ocr', String(request.force_ocr))

  // 远程服务
  if (request.server_url) formData.append('server_url', request.server_url)

  // MinerU 调试/输出选项
  if (request.draw_layout_bbox !== undefined) formData.append('draw_layout_bbox', String(request.draw_layout_bbox))
  if (request.draw_span_bbox !== undefined) formData.append('draw_span_bbox', String(request.draw_span_bbox))
  if (request.dump_markdown !== undefined) formData.append('dump_markdown', String(request.dump_markdown))
  if (request.dump_middle_json !== undefined) formData.append('dump_middle_json', String(request.dump_middle_json))
  if (request.dump_model_output !== undefined) formData.append('dump_model_output', String(request.dump_model_output))
  if (request.dump_content_list !== undefined) formData.append('dump_content_list', String(request.dump_content_list))
  if (request.dump_orig_pdf !== undefined) formData.append('dump_orig_pdf', String(request.dump_orig_pdf))

  // 兼容旧参数
  if (request.draw_layout !== undefined) formData.append('draw_layout', String(request.draw_layout))
  if (request.draw_span !== undefined) formData.append('draw_span', String(request.draw_span))

  // Video 专用参数
  if (request.keep_audio !== undefined) formData.append('keep_audio', String(request.keep_audio))
  if (request.enable_keyframe_ocr !== undefined) formData.append('enable_keyframe_ocr', String(request.enable_keyframe_ocr))
  if (request.ocr_backend) formData.append('ocr_backend', request.ocr_backend)
  if (request.keep_keyframes !== undefined) formData.append('keep_keyframes', String(request.keep_keyframes))

  // 水印去除参数
  if (request.remove_watermark !== undefined) formData.append('remove_watermark', String(request.remove_watermark))
  if (request.watermark_conf_threshold !== undefined) formData.append('watermark_conf_threshold', String(request.watermark_conf_threshold))
  if (request.watermark_dilation !== undefined) formData.append('watermark_dilation', String(request.watermark_dilation))

  // Audio 专属参数 (SenseVoice)
  if (request.enable_speaker_diarization !== undefined) formData.append('enable_speaker_diarization', String(request.enable_speaker_diarization))

  const response = await apiClient.post<SubmitTaskResponse>(
    '/api/v1/tasks/submit',
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  )
  return response.data
}

/**
 * 查询任务状态
 */
export async function getTaskStatus(
  taskId: string,
  uploadImages: boolean = false,
  format: 'markdown' | 'json' | 'both' = 'markdown'
): Promise<TaskStatusResponse> {
  const response = await apiClient.get<TaskStatusResponse>(
    `/api/v1/tasks/${taskId}`,
    {
      params: {
        upload_images: uploadImages,
        format: format
      },
    }
  )
  return response.data
}

/**
 * 取消任务 (仅 pending/processing/paused 状态有效，区别于彻底删除)
 */
export async function cancelTask(taskId: string): Promise<ApiResponse> {
  const response = await apiClient.post<ApiResponse>(`/api/v1/tasks/${taskId}/cancel`)
  return response.data
}

/**
 * 获取任务列表 (支持分页、搜索、筛选)
 */
export async function listTasks(params: TaskQueryParams): Promise<TaskListResponse> {
  const response = await apiClient.get<TaskListResponse>('/api/v1/queue/tasks', {
    params,
  })
  return response.data
}

// =================================================================
// 新增管理接口：重试、暂停、恢复、清理
// =================================================================

/**
 * 重试失败的任务
 */
export async function retryTask(taskId: string): Promise<ApiResponse> {
  const response = await apiClient.post<ApiResponse>(`/api/v1/tasks/${taskId}/retry`)
  return response.data
}

/**
 * 暂停任务 (仅 Pending 状态有效)
 */
export async function pauseTask(taskId: string): Promise<ApiResponse> {
  const response = await apiClient.post<ApiResponse>(`/api/v1/tasks/${taskId}/pause`)
  return response.data
}

/**
 * 恢复任务 (仅 Paused 状态有效)
 */
export async function resumeTask(taskId: string): Promise<ApiResponse> {
  const response = await apiClient.post<ApiResponse>(`/api/v1/tasks/${taskId}/resume`)
  return response.data
}

/**
 * 清理任务缓存 (删除磁盘文件，保留数据库记录)
 */
export async function clearTaskCache(taskId: string): Promise<ApiResponse> {
  const response = await apiClient.post<ApiResponse>(`/api/v1/tasks/${taskId}/clear-cache`)
  return response.data
}

/**
 * 一键清理所有失败的任务
 */
export async function clearFailedTasks(): Promise<{ status: string; deleted_count: number }> {
  const response = await apiClient.delete<{ status: string; deleted_count: number }>('/api/v1/tasks/failed/clear')
  return response.data
}
