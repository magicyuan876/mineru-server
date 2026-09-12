<template>
  <div class="relative w-full h-full flex flex-col bg-gray-200/80 overflow-hidden">
    <div v-if="loading || processing" class="absolute top-0 left-0 w-full h-1 bg-gray-200 z-50">
      <div class="h-full bg-primary-600 transition-all duration-300 shadow-[0_0_10px_rgba(99,102,241,0.5)]" :style="{ width: `${progress}%` }"></div>
    </div>

    <div v-if="error" class="absolute inset-0 flex flex-col items-center justify-center bg-white z-50 p-6 text-center">
      <div class="bg-red-50 p-4 rounded-full mb-3 text-red-500">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
      </div>
      <div class="text-gray-900 font-semibold text-lg mb-1">PDF 加载失败</div>
      <div class="text-gray-500 text-xs break-all max-w-md bg-gray-50 p-2 rounded border border-gray-100 mb-4">{{ error }}</div>
      <button @click="retry" class="px-5 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition shadow-sm text-sm font-medium">重新加载</button>
    </div>

    <div ref="scrollContainer" class="flex-1 overflow-y-auto w-full custom-scrollbar relative outline-none" @scroll="onScroll" tabindex="0">
      <div :style="{ height: totalHeight + 'px' }" class="relative w-full">
        <div
          v-for="page in visiblePages"
          :key="page.id"
          class="absolute left-0 w-full flex justify-center transition-opacity duration-200"
          :style="{ top: page.top + 'px', height: page.height + 'px' }"
        >
          <div class="bg-white shadow-sm relative transition-shadow hover:shadow-md" :style="{ width: page.width + 'px', height: page.height + 'px' }">

            <div v-if="!page.rendered" class="absolute inset-0 flex items-center justify-center bg-gray-50/50 z-10">
              <div class="flex flex-col items-center">
                <div class="w-8 h-8 border-4 border-gray-200 border-t-primary-600 rounded-full animate-spin mb-2"></div>
                <span class="text-gray-400 text-xs font-mono font-medium absolute mt-12">Page {{ page.id }}</span>
              </div>
            </div>

            <canvas :id="`pdf-canvas-${page.id}`" class="block w-full h-full relative z-0"></canvas>

            <div v-if="page.rendered && layoutMap[page.id]" class="absolute inset-0 z-20 pointer-events-none">
              <div
                v-for="block in layoutMap[page.id]"
                :key="block.id"
                class="absolute cursor-pointer pointer-events-auto border border-transparent hover:border-blue-400 hover:bg-blue-500/15 transition-all rounded-[2px]"
                :style="getBlockStyle(page.id, block.bbox)"
                @click.stop="$emit('block-click', block)"
                :title="`定位到解析结果 (ID: ${block.id})`"
              ></div>
            </div>

            <div
              v-if="highlightTarget && highlightTarget.pageIndex === page.id"
              class="absolute z-30 border-[3px] border-red-500 bg-red-500/20 animate-pulse pointer-events-none box-border rounded-[4px] shadow-[0_0_15px_rgba(239,68,68,0.7)]"
              :style="getBlockStyle(page.id, highlightTarget.bbox)"
            ></div>

          </div>
        </div>
      </div>
    </div>

    <div v-if="!loading && totalPages > 0" class="absolute bottom-6 right-8 bg-gray-900/75 text-white px-3 py-1.5 rounded-md text-xs backdrop-blur-md z-30 font-mono shadow-lg pointer-events-none select-none border border-white/10">
      {{ currentPage }} <span class="text-gray-400 mx-1">/</span> {{ totalPages }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onUnmounted, onMounted } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { useAuthStore } from '@/stores'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker

const authStore = useAuthStore()

const props = defineProps<{
  src: string | null
  layoutData?: any[]
}>()

const emit = defineEmits<{
  (e: 'block-click', block: any): void
}>()

const scrollContainer = ref<HTMLElement | null>(null)
let pdfProxy: pdfjsLib.PDFDocumentProxy | null = null

const loading = ref(false)
const processing = ref(false)
const progress = ref(0)
const error = ref<string | null>(null)
const highlightTarget = ref<{ pageIndex: number; bbox: any[] } | null>(null)

const scrollTop = ref(0)
const containerHeight = ref(0)
const totalHeight = ref(0) // 🚨 绝对不可丢：滚动条支柱
const totalPages = ref(0)
const globalScale = ref(1.0)
const PAGE_GAP = 16

interface PageData {
  id: number
  width: number
  height: number
  top: number // 🚨 绝对不可丢：盒子绝对定位坐标
  viewport: any
  rendered: boolean
}
const pages = ref<PageData[]>([])
const renderTasks = new Map<number, any>()

// =======================================================
// 🚀 坐标换算与数据映射核心
// =======================================================

// 将后端发来的块数据按页码归类
const layoutMap = computed(() => {
  const map: Record<number, any[]> = {}
  if (!props.layoutData) return map
  props.layoutData.forEach(block => {
    const pId = (typeof block.page_idx === 'number' ? block.page_idx : block.page_id) + 1
    if (!map[pId]) map[pId] = []
    map[pId].push(block)
  })
  return map
})

// 从 bbox 数据中推断每页的 MinerU 渲染图像宽度（取各块 x1 最大值）
// MinerU 3.0 输出的 bbox 坐标是渲染图像像素坐标，而非 PDF point 坐标
const mineruPageWidths = computed(() => {
  const widths: Record<number, number> = {}
  if (!props.layoutData) return widths
  for (const block of props.layoutData) {
    const pId = (typeof block.page_idx === 'number' ? block.page_idx : (block.page_id ?? 0)) + 1
    const bbox = block.bbox
    if (!bbox || !Array.isArray(bbox) || bbox.length === 0) continue
    let x1 = 0
    if (bbox.length === 4 && typeof bbox[0] === 'number') x1 = (bbox as number[])[2]
    else if (bbox.length === 4 && Array.isArray(bbox[0])) x1 = Math.max(...(bbox as number[][]).map((p: number[]) => p[0]))
    if (x1 > 0) widths[pId] = Math.max(widths[pId] ?? 0, x1)
  }
  return widths
})

// 智能换算比例：优先用显式 _page_width，其次从 bbox 推断渲染宽度，最后 fallback 到 globalScale
const pageOcrScales = computed(() => {
  const scales: Record<number, number> = {}
  for (const page of pages.value) {
    const providedWidth = layoutMap.value[page.id]?.[0]?._page_width
    if (providedWidth) { scales[page.id] = page.width / providedWidth; continue }
    const inferredWidth = mineruPageWidths.value[page.id]
    if (inferredWidth > 0) { scales[page.id] = page.width / inferredWidth; continue }
    scales[page.id] = globalScale.value
  }
  return scales
})

const getBlockStyle = (pageId: number, bbox: any) => {
  if (!bbox || !Array.isArray(bbox) || bbox.length === 0) return { display: 'none' }

  let x0 = 0, y0 = 0, x1 = 0, y1 = 0;

  // 兼容绝对坐标和多边形坐标
  if (bbox.length === 4 && typeof bbox[0] === 'number') {
    [x0, y0, x1, y1] = bbox as number[];
  } else if (bbox.length === 4 && Array.isArray(bbox[0])) {
    const xs = bbox.map((p: number[]) => p[0]); const ys = bbox.map((p: number[]) => p[1]);
    x0 = Math.min(...xs); y0 = Math.min(...ys); x1 = Math.max(...xs); y1 = Math.max(...ys);
  } else { return { display: 'none' } }

  const s = pageOcrScales.value[pageId] || globalScale.value;

  return {
    left: `${x0 * s}px`,
    top: `${y0 * s}px`,
    width: `${Math.max((x1 - x0) * s, 6)}px`,
    height: `${Math.max((y1 - y0) * s, 6)}px`
  }
}

// =======================================================
// 🚀 核心控制：取代 Observer 的强力 Vue 渲染逻辑
// =======================================================

// 虚拟列表控制：计算出视野内（及上下一定范围）的页面
const visiblePages = computed(() => {
  if (pages.value.length === 0) return []
  const startY = scrollTop.value - containerHeight.value * 1.5
  const endY = scrollTop.value + containerHeight.value * 2.5
  const result = []

  for (const page of pages.value) {
    const pageBottom = page.top + page.height
    if (pageBottom < startY) continue
    if (page.top > endY) break
    result.push(page)
  }
  return result
})

// 🚀 白屏杀手锏：只要 visiblePages 变化，立即强求 Vue 渲染真实的 Canvas
watch(visiblePages, (newPages, oldPages) => {
  if (!newPages || newPages.length === 0) return;

  // 1. 回收旧的页面内存
  const newIndices = new Set(newPages.map(p => p.id));
  if (oldPages) {
    oldPages.forEach(p => {
      if (!newIndices.has(p.id)) {
        const orig = pages.value.find(o => o.id === p.id)
        if (orig) orig.rendered = false
        const task = renderTasks.get(p.id);
        if (task) { task.cancel(); renderTasks.delete(p.id); }
      }
    });
  }

  // 2. 将刚进入视野的页面绘制出来
  nextTick(() => {
    newPages.forEach(p => {
      if (!p.rendered && !renderTasks.has(p.id)) {
        renderCanvas(p);
      }
    })
  })
}, { immediate: true, deep: true })

const onScroll = (e: Event) => {
  scrollTop.value = (e.target as HTMLElement).scrollTop
}

const currentPage = computed(() => {
  if (pages.value.length === 0) return 0
  const center = scrollTop.value + (containerHeight.value / 3)
  const page = pages.value.find(p => center >= p.top && center <= (p.top + p.height + PAGE_GAP))
  return page ? page.id : 1
})

// =======================================================
// 🚀 加载与骨架构建
// =======================================================

const loadPdf = async (url: string) => {
  if (!url) return
  error.value = null; loading.value = true; progress.value = 10;
  pages.value = []; renderTasks.clear();
  if (pdfProxy) { pdfProxy.destroy(); pdfProxy = null }

  try {
    // 文件服务接口需要鉴权：pdf.js 通过 XHR 拉取，显式携带 Authorization 头
    const httpHeaders: Record<string, string> = authStore.token
      ? { Authorization: `Bearer ${authStore.token}` }
      : {}
    const loadingTask = pdfjsLib.getDocument({ url, httpHeaders, isEvalSupported: false })
    loadingTask.onProgress = (p) => { if (p.total) progress.value = 10 + (p.loaded / p.total) * 60 }
    pdfProxy = await loadingTask.promise
    totalPages.value = pdfProxy.numPages
    progress.value = 80
    await buildPageSkeletons()
  } catch (err: any) {
    error.value = 'PDF解析失败，请检查文件格式。'
  } finally {
    loading.value = false; progress.value = 100
  }
}

// 轮询等待宽度，然后算出包含 top 与 height 的骨架
const buildPageSkeletons = async (retryCount = 0) => {
  if (!pdfProxy || !scrollContainer.value) return
  processing.value = true

  const containerW = scrollContainer.value.clientWidth - 40
  // 必须等到容器被撑开，否则一直重试
  if (containerW <= 0) {
    if (retryCount < 50) setTimeout(() => buildPageSkeletons(retryCount + 1), 50)
    return
  }
  containerHeight.value = scrollContainer.value.clientHeight

  const newPages: PageData[] = []

  const page1 = await pdfProxy.getPage(1)
  const baseViewport = page1.getViewport({ scale: 1 })
  const fitScale = Math.min(containerW / baseViewport.width, 1.8)
  globalScale.value = fitScale

  let currentTop = PAGE_GAP

  // 🚀 为每一页计算出绝对的 Top 与 Height，并推入数组
  for (let i = 1; i <= totalPages.value; i++) {
    const p = await pdfProxy.getPage(i)
    const vp = p.getViewport({ scale: fitScale })
    newPages.push({
      id: i,
      width: vp.width,
      height: vp.height,
      top: currentTop, // 这个保证了绝对定位
      viewport: vp,
      rendered: false
    })
    currentTop += vp.height + PAGE_GAP
  }

  pages.value = newPages
  totalHeight.value = currentTop // 这个保证了滚动条的出现
  processing.value = false
}

// 执行 PDF.js 的页面渲染
const renderCanvas = async (pageInfo: PageData) => {
  if (!pdfProxy) return

  const canvasId = `pdf-canvas-${pageInfo.id}`
  const canvas = document.getElementById(canvasId) as HTMLCanvasElement
  // 防御性拦截：如果因为页面切换太快 DOM 还不在，就放弃渲染
  if (!canvas) return

  renderTasks.set(pageInfo.id, true)
  const origPage = pages.value.find(p => p.id === pageInfo.id)

  try {
    const page = await pdfProxy.getPage(pageInfo.id)
    const dpr = window.devicePixelRatio || 1
    canvas.width = pageInfo.width * dpr
    canvas.height = pageInfo.height * dpr
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const renderCtx = { canvasContext: ctx, viewport: pageInfo.viewport, transform: [dpr, 0, 0, dpr, 0, 0] }
    await page.render(renderCtx).promise

    // 渲染成功后，更新状态，让热区盖上来
    if (origPage) origPage.rendered = true
  } catch (err: any) {
    if (err.name !== 'RenderingCancelledException') console.warn(`Render Page ${pageInfo.id} failed:`, err)
    if (origPage) origPage.rendered = false
  } finally {
    renderTasks.delete(pageInfo.id)
  }
}

// =======================================================
// 暴露给外部的 API
// =======================================================

const highlightBlock = (pageIndex: number, bbox: any) => {
  if (!scrollContainer.value) return
  highlightTarget.value = { pageIndex, bbox }

  const pageNode = pages.value.find(p => p.id === pageIndex)
  if (pageNode) {
    let blockY = 0
    if (bbox && bbox.length === 4) {
      blockY = typeof bbox[0] === 'number' ? bbox[1] : Math.min(...bbox.map((p:any)=>p[1]))
    }
    const s = pageOcrScales.value[pageIndex] || globalScale.value;
    const targetScroll = pageNode.top + (blockY * s) - (containerHeight.value / 3)

    scrollContainer.value.scrollTo({ top: Math.max(0, targetScroll), behavior: 'smooth' })

    setTimeout(() => { highlightTarget.value = null }, 3000)
  }
}

// 重启大小监视：用于在浏览器窗口大小改变时重绘
let resizeTimeout: any = null
const handleResize = () => {
  clearTimeout(resizeTimeout)
  resizeTimeout = setTimeout(() => {
    if (pdfProxy && scrollContainer.value && scrollContainer.value.clientWidth > 0) {
      buildPageSkeletons()
    }
  }, 200)
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

watch(() => props.src, (url) => { if(url) loadPdf(url) }, { immediate: true })

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (pdfProxy) { pdfProxy.destroy(); pdfProxy = null }
  renderTasks.clear()
})

defineExpose({ highlightBlock })
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 8px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; background-clip: content-box; border: 2px solid transparent;}
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
</style>
