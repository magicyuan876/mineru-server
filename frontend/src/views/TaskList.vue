<template>
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 animate-fade-in">
    <div class="mb-8 flex flex-col md:flex-row md:items-end justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <List class="w-7 h-7 text-primary-600" />
          {{ $t('task.taskList') }}
        </h1>
        <p class="mt-1 text-sm text-gray-500">{{ $t('task.taskListDesc') }}</p>
      </div>

      <div class="flex flex-wrap items-center gap-3">
        <label class="flex items-center cursor-pointer bg-white px-3 py-2 rounded-lg border border-gray-200 shadow-sm hover:bg-gray-50 transition-colors" :title="$t('common.autoRefreshLabel')">
          <input type="checkbox" v-model="autoRefresh" class="sr-only">
          <div class="relative w-8 h-4 transition-colors rounded-full" :class="autoRefresh ? 'bg-green-500' : 'bg-gray-300'">
            <div class="absolute left-0.5 top-0.5 w-3 h-3 bg-white rounded-full transition-transform shadow-sm" :class="autoRefresh ? 'translate-x-4' : 'translate-x-0'"></div>
          </div>
          <span class="ml-2 text-xs font-medium text-gray-600 select-none">{{ $t('common.autoRefreshLabel') }}</span>
        </label>

        <button
          @click="confirmClearFailed"
          :disabled="actionLoading"
          class="btn bg-white text-red-600 border border-gray-200 hover:bg-red-50 hover:border-red-200 btn-sm flex items-center shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          :title="$t('task.clearFailedTasks')"
        >
          <Trash2 :class="{ 'animate-spin': actionLoading && currentActionType === 'clearFailed' }" class="w-4 h-4 mr-1.5" />
          <span class="hidden sm:inline">{{ $t('task.clearFailedTasks') }}</span>
        </button>

        <button
          @click="refreshTasks(true)"
          :disabled="loading"
          class="btn bg-white text-gray-700 border border-gray-200 hover:bg-gray-50 btn-sm flex items-center shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RefreshCw :class="{ 'animate-spin': loading }" class="w-4 h-4 mr-1.5" />
          {{ $t('common.refresh') }}
        </button>

        <router-link to="/tasks/submit" class="btn btn-primary btn-sm flex items-center shadow-sm shadow-primary-500/30">
          <Plus class="w-4 h-4 mr-1.5" />
          {{ $t('task.submitTask') }}
        </router-link>
      </div>
    </div>

    <div class="card mb-6 shadow-sm border-gray-100 bg-white/80 backdrop-blur-sm">
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 p-4">
        <div>
          <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{{ $t('task.filterByStatus') }}</label>
          <div class="relative group">
            <select
              v-model="filters.status"
              @change="applyFilters"
              class="w-full pl-9 pr-8 py-2.5 bg-gray-50 border border-gray-200 rounded-lg focus:bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors text-sm appearance-none outline-none cursor-pointer"
            >
              <option value="">{{ $t('task.allStatus') }}</option>
              <option value="pending">{{ $t('status.pending') }}</option>
              <option value="paused">{{ $t('status.paused') }}</option> <option value="processing">{{ $t('status.processing') }}</option>
              <option value="completed">{{ $t('status.completed') }}</option>
              <option value="failed">{{ $t('status.failed') }}</option>
              <option value="cancelled">{{ $t('status.cancelled') }}</option>
            </select>
            <Filter class="absolute left-3 top-2.5 w-4 h-4 text-gray-400 pointer-events-none group-hover:text-primary-500 transition-colors" />
            <ChevronDown class="absolute right-2.5 top-3 w-4 h-4 text-gray-400 pointer-events-none" />
          </div>
        </div>

        <div>
          <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{{ $t('task.backend') }}</label>
          <div class="relative group">
            <select
              v-model="filters.backend"
              @change="applyFilters"
              class="w-full pl-9 pr-8 py-2.5 bg-gray-50 border border-gray-200 rounded-lg focus:bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors text-sm appearance-none outline-none cursor-pointer"
            >
              <option value="">{{ $t('task.allBackends') }}</option>
              <optgroup label="MinerU Standard">
                <option value="pipeline">Pipeline (PDF)</option>
                <option value="hybrid-auto-engine">Hybrid (High Prec.)</option>
              </optgroup>
              <optgroup label="Visual Models">
                <option value="vlm-auto-engine">VLM Auto</option>
              </optgroup>
              <optgroup label="Media">
                <option value="sensevoice">SenseVoice (Audio)</option>
                <option value="video">Video Processing</option>
              </optgroup>
            </select>
            <Server class="absolute left-3 top-2.5 w-4 h-4 text-gray-400 pointer-events-none group-hover:text-primary-500 transition-colors" />
            <ChevronDown class="absolute right-2.5 top-3 w-4 h-4 text-gray-400 pointer-events-none" />
          </div>
        </div>

        <div class="sm:col-span-2">
          <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{{ $t('common.search') }}</label>
          <div class="relative group">
            <input
              v-model="filters.search"
              @input="applyFilters"
              type="text"
              :placeholder="$t('common.searchPlaceholder')"
              class="w-full pl-9 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg focus:bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors text-sm outline-none"
            >
            <Search class="absolute left-3 top-2.5 w-4 h-4 text-gray-400 pointer-events-none group-hover:text-primary-500 transition-colors" />
          </div>
        </div>
      </div>
    </div>

    <div class="card shadow-lg shadow-gray-100/50 border-gray-100 overflow-hidden min-h-[400px]">

      <div v-if="selectedTasks.length > 0" class="bg-primary-50/50 px-6 py-3 border-b border-primary-100 flex items-center justify-between transition-all animate-fade-in">
        <div class="flex items-center text-primary-800 text-sm font-medium">
          <CheckSquare class="w-4 h-4 mr-2" />
          {{ $t('common.selected') }} <span class="font-bold mx-1">{{ selectedTasks.length }}</span> {{ $t('common.items') }}
        </div>
        <div class="flex gap-2">
          <button
            @click="batchCancel"
            :disabled="actionLoading"
            class="bg-white border border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700 px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <XCircle :class="{ 'animate-spin': actionLoading && currentActionType === 'batchCancel' }" class="w-3.5 h-3.5 mr-1.5" />
            {{ $t('task.batchCancel') }}
          </button>
          <button
            @click="selectedTasks = []; selectAll = false"
            class="text-gray-500 hover:text-gray-700 hover:bg-gray-100 px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
          >
            {{ $t('common.deselect') }}
          </button>
        </div>
      </div>

      <div v-if="loading && tasks.length === 0" class="flex flex-col items-center justify-center py-40">
        <LoadingSpinner size="lg" :text="$t('common.loading')" />
      </div>

      <div v-else-if="tasks.length === 0" class="flex flex-col items-center justify-center py-32 text-gray-500">
        <div class="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center mb-4 shadow-inner">
          <FileQuestion class="w-10 h-10 text-gray-300" />
        </div>
        <p class="text-lg font-medium text-gray-900">{{ $t('task.noTasks') }}</p>
        <p class="text-sm mt-1 max-w-sm text-center text-gray-400">{{ $t('task.noMatchingTasks') }}</p>
        <button @click="clearFilters" class="mt-6 px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors shadow-sm">
          {{ $t('task.clearFilters') }}
        </button>
      </div>

      <div v-else class="overflow-x-auto custom-scrollbar">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50/80 backdrop-blur">
            <tr>
              <th scope="col" class="px-6 py-4 text-left w-12">
                <input
                  v-model="selectAll"
                  @change="toggleSelectAll"
                  type="checkbox"
                  class="rounded border-gray-300 text-primary-600 focus:ring-primary-500 w-4 h-4 cursor-pointer transition-colors"
                >
              </th>
              <th scope="col" class="table-th">{{ $t('task.fileName') }}</th>
              <th scope="col" class="table-th w-32">{{ $t('task.status') }}</th>
              <th scope="col" class="table-th w-32">{{ $t('task.backend') }}</th>
              <th scope="col" class="table-th w-40">{{ $t('task.timeInfo') }}</th>
              <th scope="col" class="table-th text-right w-48">{{ $t('task.actions') }}</th>
            </tr>
          </thead>
          <tbody class="bg-white divide-y divide-gray-100">
            <tr
              v-for="task in tasks"
              :key="task.task_id"
              :class="{'bg-primary-50/20': selectedTasks.includes(task.task_id)}"
              class="hover:bg-gray-50 transition-colors group"
            >
              <td class="px-6 py-4 whitespace-nowrap">
                <input
                  v-model="selectedTasks"
                  :value="task.task_id"
                  type="checkbox"
                  class="rounded border-gray-300 text-primary-600 focus:ring-primary-500 w-4 h-4 cursor-pointer transition-colors"
                >
              </td>
              <td class="px-6 py-4">
                <div class="flex items-start">
                  <div class="p-2.5 bg-gray-100 rounded-xl mr-3 group-hover:bg-white group-hover:shadow-md group-hover:text-primary-600 transition-all text-gray-500">
                    <FileText class="w-5 h-5" />
                  </div>
                  <div class="min-w-0">
                    <div class="text-sm font-semibold text-gray-900 truncate max-w-[200px] sm:max-w-[280px]" :title="task.file_name">
                      {{ task.file_name }}
                    </div>
                    <div class="flex items-center mt-1 space-x-2">
                        <span class="text-xs text-gray-400 font-mono bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">
                         {{ task.task_id.slice(0, 8) }}
                        </span>
                        <button @click="copyToClipboard(task.task_id)" class="opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-primary-600" :title="$t('common.copy')">
                          <Copy class="w-3 h-3" />
                        </button>
                    </div>
                  </div>
                </div>
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <StatusBadge :status="task.status" />
                <div v-if="task.result_path === 'CLEARED'" class="mt-1">
                    <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-500">
                      <Eraser class="w-3 h-3 mr-1" />
                      {{ $t('status.cleared') }}
                    </span>
                </div>
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">
                  {{ formatBackendName(task.backend) }}
                </span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                <div class="flex flex-col">
                  <span class="text-gray-900 font-medium">{{ formatRelativeTime(task.created_at) }}</span>
                  <span v-if="task.completed_at" class="text-xs text-gray-400 mt-0.5 flex items-center">
                    <Clock class="w-3 h-3 mr-1" />
                    {{ formatDuration(task.created_at, task.completed_at) }}
                  </span>
                </div>
              </td>

              <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                <div class="flex items-center justify-end gap-1 opacity-80 group-hover:opacity-100 transition-opacity">

                  <router-link
                    :to="`/tasks/${task.task_id}`"
                    class="btn-icon text-gray-500 hover:text-primary-600 hover:bg-primary-50"
                    :title="$t('task.viewDetail')"
                  >
                    <Eye class="w-4 h-4" />
                  </router-link>

                  <button
                    v-if="task.status === 'pending'"
                    @click="handleAction('pause', task)"
                    :disabled="isActionLoading(task.task_id)"
                    class="btn-icon text-amber-500 hover:text-amber-600 hover:bg-amber-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    :title="$t('task.pauseTask')"
                  >
                    <RefreshCw v-if="isActionLoading(task.task_id, 'pause')" class="w-4 h-4 animate-spin" />
                    <Pause v-else class="w-4 h-4" />
                  </button>

                  <button
                    v-if="task.status === 'paused'"
                    @click="handleAction('resume', task)"
                    :disabled="isActionLoading(task.task_id)"
                    class="btn-icon text-green-500 hover:text-green-600 hover:bg-green-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    :title="$t('task.resumeTask')"
                  >
                    <RefreshCw v-if="isActionLoading(task.task_id, 'resume')" class="w-4 h-4 animate-spin" />
                    <Play v-else class="w-4 h-4" />
                  </button>

                  <button
                    v-if="task.status === 'failed'"
                    @click="handleAction('retry', task)"
                    :disabled="isActionLoading(task.task_id)"
                    class="btn-icon text-blue-500 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    :title="$t('task.retryTask')"
                  >
                    <RefreshCw v-if="isActionLoading(task.task_id, 'retry')" class="w-4 h-4 animate-spin" />
                    <RotateCw v-else class="w-4 h-4" />
                  </button>

                  <button
                    v-if="['completed', 'failed'].includes(task.status) && task.result_path !== 'CLEARED'"
                    @click="handleAction('clearCache', task)"
                    :disabled="isActionLoading(task.task_id)"
                    class="btn-icon text-orange-400 hover:text-orange-500 hover:bg-orange-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    :title="$t('task.clearCache')"
                  >
                    <RefreshCw v-if="isActionLoading(task.task_id, 'clearCache')" class="w-4 h-4 animate-spin" />
                    <Eraser v-else class="w-4 h-4" />
                  </button>

                  <button
                    v-if="['pending', 'processing'].includes(task.status)"
                    @click="handleAction('cancel', task)"
                    :disabled="isActionLoading(task.task_id)"
                    class="btn-icon text-gray-400 hover:text-red-600 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
                    :title="$t('task.cancelTask')"
                  >
                    <RefreshCw v-if="isActionLoading(task.task_id, 'cancel')" class="w-4 h-4 animate-spin" />
                    <XCircle v-else class="w-4 h-4" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="total > 0" class="bg-gray-50/80 px-6 py-4 border-t border-gray-200 flex items-center justify-between backdrop-blur">
        <div class="text-xs text-gray-500 hidden sm:block">
           {{ $t('common.pagination', { start: (currentPage - 1) * pageSize + 1, end: Math.min(currentPage * pageSize, total), total: total }) }}
        </div>
        <div class="flex gap-2 w-full sm:w-auto justify-between sm:justify-end">
          <button
            @click="changePage(currentPage - 1)"
            :disabled="currentPage === 1"
            class="page-btn"
          >
            <ChevronLeft class="w-4 h-4" />
          </button>
          <div class="flex items-center px-4 bg-white border border-gray-200 rounded-md shadow-sm">
            <span class="text-sm font-medium text-gray-700">{{ currentPage }}</span>
            <span class="text-sm text-gray-400 mx-2">/</span>
            <span class="text-sm text-gray-500">{{ totalPages }}</span>
          </div>
          <button
            @click="changePage(currentPage + 1)"
            :disabled="currentPage === totalPages"
            class="page-btn"
          >
            <ChevronRight class="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      v-model="showConfirmDialog"
      :title="confirmDialogTitle"
      :message="confirmDialogMessage"
      :type="confirmDialogType"
      @confirm="executeConfirmedAction"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useTaskStore } from '@/stores/taskStore'
import { useI18n } from 'vue-i18n'
import { formatRelativeTime, formatBackendName, formatDuration } from '@/utils/format'
import StatusBadge from '@/components/StatusBadge.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import {
  Search, RefreshCw, Plus, FileText, Eye, FileQuestion,
  ChevronLeft, ChevronRight, Filter, Server, CheckSquare,
  XCircle, Copy, Trash2, Play, Pause, RotateCw, Eraser, List, Clock, ChevronDown
} from 'lucide-vue-next'
import type { TaskStatus, Backend, Task } from '@/api/types'

const { t } = useI18n()
const taskStore = useTaskStore()

// ----------------------------------------------------------------
// 状态定义
// ----------------------------------------------------------------
const tasks = computed(() => taskStore.tasks)
const total = computed(() => taskStore.total)
const loading = ref(false)
const autoRefresh = ref(false)
let refreshInterval: number | null = null

// 操作 Loading 状态管理
const actionLoading = ref(false)
const currentActionTaskId = ref<string | null>(null)
const currentActionType = ref<string | null>(null)

const filters = ref({
  status: '' as TaskStatus | '',
  backend: '' as Backend | '',
  search: '',
})

const pageSize = 20
const currentPage = ref(1)
const totalPages = computed(() => Math.ceil(total.value / pageSize) || 1)

// ----------------------------------------------------------------
// 批量选择逻辑
// ----------------------------------------------------------------
const selectedTasks = ref<string[]>([])
const selectAll = ref(false)

function toggleSelectAll() {
  if (selectAll.value) {
    selectedTasks.value = tasks.value.map(t => t.task_id)
  } else {
    selectedTasks.value = []
  }
}

watch(currentPage, () => {
  selectAll.value = false
  selectedTasks.value = []
})

// ----------------------------------------------------------------
// 核心：数据获取
// ----------------------------------------------------------------
async function refreshTasks(forceLoading = false) {
  if (forceLoading) loading.value = true

  try {
    await taskStore.fetchTasks({
      page: currentPage.value,
      page_size: pageSize,
      status: filters.value.status || undefined,
      backend: filters.value.backend || undefined,
      search: filters.value.search || undefined
    })
  } catch (error) {
    console.error("Failed to fetch tasks", error)
  } finally {
    loading.value = false
  }
}

function changePage(page: number) {
  if (page >= 1 && page <= totalPages.value) {
    currentPage.value = page
    refreshTasks(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

function applyFilters() {
  currentPage.value = 1
  refreshTasks(true)
}

function clearFilters() {
  filters.value.status = ''
  filters.value.backend = ''
  filters.value.search = ''
  applyFilters()
}

// ----------------------------------------------------------------
// 操作处理逻辑
// ----------------------------------------------------------------
const showConfirmDialog = ref(false)
const confirmDialogTitle = ref('')
const confirmDialogMessage = ref('')
const confirmDialogType = ref<'info' | 'warning' | 'danger'>('info')
let pendingAction: (() => Promise<void>) | null = null

// 检查当前任务是否正在执行特定操作
function isActionLoading(taskId: string, actionType?: string) {
  if (!actionLoading.value) return false
  if (taskId !== currentActionTaskId.value) return false
  if (actionType && actionType !== currentActionType.value) return false
  return true
}

/**
 * 统一处理单个任务的操作
 */
function handleAction(action: 'retry' | 'pause' | 'resume' | 'cancel' | 'clearCache', task: Task) {
  // 设置待执行的 Action
  const execute = async () => {
    actionLoading.value = true
    currentActionTaskId.value = task.task_id
    currentActionType.value = action

    try {
      switch (action) {
        case 'retry': await taskStore.retryTask(task.task_id); break;
        case 'pause': await taskStore.pauseTask(task.task_id); break;
        case 'resume': await taskStore.resumeTask(task.task_id); break;
        case 'clearCache': await taskStore.clearTaskCache(task.task_id); break;
        case 'cancel': await taskStore.cancelTask(task.task_id); break;
      }
      await refreshTasks() // 操作后刷新列表
    } catch (error) {
      console.error(`Action ${action} failed:`, error)
      alert(`Action failed: ${error}`) // 简单提示，建议替换为 Toast
    } finally {
      actionLoading.value = false
      currentActionTaskId.value = null
      currentActionType.value = null
    }
  }

  // 根据操作类型决定是否显示确认框
  switch (action) {
    case 'retry':
      pendingAction = execute
      confirmDialogTitle.value = t('task.retryTask')
      confirmDialogMessage.value = t('task.confirmRetry')
      confirmDialogType.value = 'info'
      showConfirmDialog.value = true
      break
    case 'pause':
      // 暂停通常不需要确认，直接执行，或者也可以加上确认
      pendingAction = execute
      confirmDialogTitle.value = t('task.pauseTask')
      confirmDialogMessage.value = t('task.confirmPause')
      confirmDialogType.value = 'warning'
      showConfirmDialog.value = true
      break
    case 'resume':
      // 继续通常不需要确认，直接执行
      execute()
      break
    case 'clearCache':
      pendingAction = execute
      confirmDialogTitle.value = t('task.clearCache')
      confirmDialogMessage.value = t('task.confirmClearCache')
      confirmDialogType.value = 'danger'
      showConfirmDialog.value = true
      break
    case 'cancel':
      pendingAction = execute
      confirmDialogTitle.value = t('task.cancelTask')
      confirmDialogMessage.value = t('task.confirmCancel')
      confirmDialogType.value = 'danger'
      showConfirmDialog.value = true
      break
  }
}

/**
 * 一键清理失败任务
 */
function confirmClearFailed() {
  pendingAction = async () => {
    actionLoading.value = true
    currentActionType.value = 'clearFailed'
    try {
      await taskStore.clearFailedTasks()
      // 强制重新加载列表，并重置到第一页
      currentPage.value = 1
      await refreshTasks(true)
    } finally {
      actionLoading.value = false
      currentActionType.value = null
    }
  }
  confirmDialogTitle.value = t('task.clearFailedTasks')
  confirmDialogMessage.value = t('task.confirmClearFailed')
  confirmDialogType.value = 'danger'
  showConfirmDialog.value = true
}

/**
 * 批量取消
 */
function batchCancel() {
  const pendingIds = selectedTasks.value.filter(id => {
    const task = tasks.value.find(t => t.task_id === id)
    return task?.status === 'pending'
  })

  if (pendingIds.length === 0) {
    alert(t('task.noPendingTasksToCancel'))
    return
  }

  pendingAction = async () => {
    actionLoading.value = true
    currentActionType.value = 'batchCancel'
    try {
      for (const id of pendingIds) {
        await taskStore.cancelTask(id)
      }
      selectedTasks.value = []
      selectAll.value = false
      await refreshTasks(true)
    } finally {
      actionLoading.value = false
      currentActionType.value = null
    }
  }

  confirmDialogTitle.value = t('task.batchCancel')
  confirmDialogMessage.value = t('task.confirmBatchCancel', { count: pendingIds.length })
  confirmDialogType.value = 'danger'
  showConfirmDialog.value = true
}

/**
 * 执行确认的操作
 */
async function executeConfirmedAction() {
  if (pendingAction) {
    try {
      await pendingAction()
    } catch (err) {
      console.error('Action failed:', err)
    } finally {
      pendingAction = null
    }
  }
}

// ----------------------------------------------------------------
// 生命周期与工具
// ----------------------------------------------------------------
watch(autoRefresh, (newVal) => {
  localStorage.setItem('task_list_auto_refresh', String(newVal))
  if (newVal) {
    refreshTasks(false)
    refreshInterval = window.setInterval(() => refreshTasks(false), 5000)
  } else {
    if (refreshInterval) {
      clearInterval(refreshInterval)
      refreshInterval = null
    }
  }
})

onMounted(async () => {
  await refreshTasks(true)
  if (localStorage.getItem('task_list_auto_refresh') === 'true') {
    autoRefresh.value = true
  }
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text)
  // 可选：添加 Toast 提示
}
</script>

<style scoped>
.btn-icon { @apply p-1.5 rounded transition-all duration-200; }
.table-th { @apply px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider select-none; }
.page-btn { @apply p-2 bg-white border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-50 hover:text-primary-600 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-all; }
.animate-fade-in { animation: fadeIn 0.5s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

/* 自定义滚动条 */
.custom-scrollbar::-webkit-scrollbar { height: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: #e5e7eb; border-radius: 3px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #d1d5db; }
</style>
