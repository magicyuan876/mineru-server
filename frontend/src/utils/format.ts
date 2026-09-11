/**
 * 格式化工具函数
 */
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import 'dayjs/locale/zh-cn'

// 初始化 dayjs 插件
dayjs.extend(relativeTime)
dayjs.extend(utc)
dayjs.extend(timezone)
dayjs.locale('zh-cn')

/**
 * 格式化日期时间
 * 将 UTC 时间转换为本地时间显示
 * 格式: YYYY-MM-DD HH:mm:ss
 */
export function formatDateTime(date: string | null | undefined): string {
  if (!date) return '-'
  return dayjs.utc(date).local().format('YYYY-MM-DD HH:mm:ss')
}

/**
 * 格式化日期
 * 格式: YYYY-MM-DD
 */
export function formatDate(date: string | null | undefined): string {
  if (!date) return '-'
  return dayjs.utc(date).local().format('YYYY-MM-DD')
}

/**
 * 格式化相对时间 (例如: "3分钟前")
 */
export function formatRelativeTime(date: string | null | undefined): string {
  if (!date) return '-'
  return dayjs.utc(date).local().fromNow()
}

/**
 * 格式化文件大小
 * 自动转换 B, KB, MB, GB, TB
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'

  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

/**
 * 格式化持续时间
 * 计算开始和结束时间的差值，显示为秒、分或小时
 */
export function formatDuration(startTime: string | null, endTime: string | null): string {
  if (!startTime || !endTime) return '-'

  const start = dayjs.utc(startTime)
  const end = dayjs.utc(endTime)
  const seconds = end.diff(start, 'second')

  if (seconds < 60) {
    return `${seconds}秒`
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${minutes}分${secs}秒`
  } else {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${hours}小时${minutes}分`
  }
}

/**
 * 格式化 Backend 名称 (用于 UI 显示)
 * 映射后端标识符到可读性更强的名称
 */
export function formatBackendName(backend: string): string {
  const backendNames: Record<string, string> = {
    // 自动
    'auto': 'Auto Detect (自动)',

    // MinerU 核心
    'pipeline': 'Pipeline (Standard)',
    'vlm-auto-engine': 'MinerU VLM 2.5 (Local)',
    'hybrid-auto-engine': 'Hybrid High-Prec (Local)',

    // 远程模式
    'vlm-http-client': 'MinerU VLM (Remote)',
    'hybrid-http-client': 'Hybrid (Remote)',

    // 音视频
    'sensevoice': 'SenseVoice (Audio)',
    'video': 'Video Analysis',

    // 专业格式
    'fasta': 'Bio: FASTA',
    'genbank': 'Bio: GenBank',

    // 兼容旧版
    'vlm-transformers': 'VLM Transformers (Legacy)',
    'vlm-vllm-engine': 'VLM vLLM (Legacy)',
  }

  return backendNames[backend] || backend
}
