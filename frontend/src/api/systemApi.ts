/**
 * 系统配置 API
 */

import type {
  SystemConfigResponse,
  SystemConfigUpdateRequest,
  EnginesResponse,
  ImageCaptionConfigResponse,
  ImageCaptionTestResult,
} from './types'
import apiClient from './client'

/**
 * 获取引擎信息（可用引擎列表 + 运行环境版本信息）
 */
export async function getEnginesInfo(): Promise<EnginesResponse> {
  const response = await apiClient.get('/api/v1/engines')
  return response.data
}

/**
 * 获取系统配置（公开接口）
 */
export async function getSystemConfig(): Promise<SystemConfigResponse> {
  const response = await apiClient.get('/api/v1/auth/system/config')
  return response.data
}

/**
 * 更新系统配置（管理员）
 */
export async function updateSystemConfig(
  config: SystemConfigUpdateRequest
): Promise<SystemConfigResponse> {
  const response = await apiClient.post('/api/v1/auth/system/config', config)
  return response.data
}

/**
 * 获取图片描述（多模态大模型）配置（管理员）
 */
export async function getImageCaptionConfig(): Promise<ImageCaptionConfigResponse> {
  const response = await apiClient.get('/api/v1/auth/system/config/image-caption')
  return response.data
}

/**
 * 测试图片描述模型连接（管理员）
 * api_key 未修改时传掩码值，后端回落到已存值
 */
export async function testImageCaptionConnection(data: {
  api_base?: string
  api_key?: string
  model?: string
  timeout?: number
}): Promise<ImageCaptionTestResult> {
  const response = await apiClient.post('/api/v1/auth/system/config/image-caption/test', data)
  return response.data
}

/**
 * 上传系统 Logo（管理员）
 */
export async function uploadSystemLogo(
  file: File
): Promise<{ success: boolean; logo_url: string; message: string }> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await apiClient.post('/api/v1/auth/system/logo/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}
