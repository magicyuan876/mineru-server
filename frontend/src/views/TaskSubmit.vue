<template>
  <div class="max-w-5xl mx-auto px-4 py-6 animate-fade-in">
    <div class="mb-6 flex justify-between items-end">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 tracking-tight">{{ $t('task.submitTask') }}</h1>
        <p class="mt-1 text-sm text-gray-500">{{ $t('task.processingOptions') }}</p>
      </div>
      <button
        @click="resetConfig"
        class="text-xs text-gray-500 hover:text-primary-600 underline transition-colors flex items-center"
        :title="$t('task.resetConfig')"
      >
        <RotateCcw class="w-3 h-3 mr-1" />
        {{ $t('common.reset') }}
      </button>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">

      <div class="lg:col-span-5 order-2 lg:order-1">
        <div class="card shadow-sm hover:shadow-md transition-shadow duration-200 h-full flex flex-col">
          <div class="p-4 border-b border-gray-100 bg-gray-50 rounded-t-lg">
            <h2 class="text-lg font-semibold text-gray-800 flex items-center">
              <Upload class="w-5 h-5 mr-2 text-primary-600" />
              {{ $t('task.selectFile') }}
            </h2>
          </div>
          <div class="p-6 flex-1 flex flex-col">
            <FileUploader
              ref="fileUploader"
              :multiple="true"
              :acceptHint="$t('task.supportedFormatsHint')"
              @update:files="onFilesChange"
              class="flex-1"
            />

            <div class="mt-6 pt-6 border-t border-gray-100">
              <button
                @click="submitTasks"
                :disabled="files.length === 0 || submitting"
                class="w-full btn btn-primary py-3 text-base font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center shadow-sm hover:shadow-md transition-all transform active:scale-[0.98]"
              >
                <Loader v-if="submitting" class="w-5 h-5 mr-2 animate-spin" />
                <Send v-else class="w-5 h-5 mr-2" />
                {{ submitting ? $t('common.loading') : `${$t('task.submitTask')} (${files.length})` }}
              </button>
              <p v-if="files.length === 0" class="text-center text-xs text-gray-400 mt-2">
                {{ $t('task.pleaseSelectFile') }}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div class="lg:col-span-7 order-1 lg:order-2">
        <div class="card shadow-sm hover:shadow-md transition-shadow duration-200 bg-white">
          <div class="p-4 border-b border-gray-100 bg-gray-50 rounded-t-lg flex justify-between items-center">
            <h2 class="text-lg font-semibold text-gray-800 flex items-center">
              <Settings class="w-5 h-5 mr-2 text-primary-600" />
              {{ $t('task.processingOptions') }}
            </h2>
            <span class="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded border border-blue-100 font-mono">
              {{ config.backend }}
            </span>
          </div>

          <div class="p-6 space-y-6">

            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
               <button
                 v-for="preset in presets"
                 :key="preset.id"
                 @click="applyPreset(preset)"
                 :class="['p-2 rounded-lg border text-left transition-all relative overflow-hidden group',
                           currentPreset === preset.id ? 'border-primary-500 bg-primary-50 ring-1 ring-primary-500' : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50']"
               >
                 <div class="text-xl mb-1">{{ preset.icon }}</div>
                 <div class="text-xs font-bold text-gray-800">{{ preset.name }}</div>
                 <div class="text-[10px] text-gray-500 leading-tight mt-0.5">{{ preset.desc }}</div>
                 <div v-if="currentPreset === preset.id" class="absolute top-1 right-1 text-primary-600">
                    <CheckCircle class="w-3 h-3" />
                 </div>
               </button>
            </div>

            <hr class="border-gray-100" />

            <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div class="col-span-1 md:col-span-2">
                <label class="block text-sm font-bold text-gray-800 mb-1.5">{{ $t('task.backend') }}</label>
                <div class="relative">
                  <select
                    v-model="config.backend"
                    @change="onBackendChange"
                    class="w-full pl-3 pr-8 py-3 bg-white border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 transition-colors text-sm font-medium shadow-sm"
                  >
                    <option value="auto">{{ $t('task.backendAuto') }}</option>

                    <optgroup label="MinerU (Local)">
                      <option value="pipeline">{{ $t('task.backendPipeline') }}</option>
                      <option value="hybrid-auto-engine">{{ $t('task.backendHybridAutoEngine') }}</option>
                      <option value="vlm-auto-engine">{{ $t('task.backendVlmAutoEngine') }}</option>
                    </optgroup>

                    <optgroup label="MinerU (Remote Client)">
                      <option value="hybrid-http-client">{{ $t('task.backendHybridHttpClient') }}</option>
                      <option value="vlm-http-client">{{ $t('task.backendVlmHttpClient') }}</option>
                    </optgroup>

                    <optgroup :label="$t('task.groupAudioVideo')">
                      <option value="sensevoice">{{ $t('task.backendSenseVoice') }}</option>
                      <option value="video">{{ $t('task.backendVideo') }}</option>
                    </optgroup>

                    <optgroup :label="$t('task.groupProfessional')">
                      <option value="fasta">{{ $t('task.backendFasta') }}</option>
                      <option value="genbank">{{ $t('task.backendGenBank') }}</option>
                    </optgroup>
                  </select>
                  <div class="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none">
                    <ChevronDown class="w-4 h-4 text-gray-500" />
                  </div>
                </div>
                <p class="mt-2 text-xs text-gray-600 bg-gray-50 p-2 rounded border border-gray-100 flex items-start">
                  <Info class="w-3.5 h-3.5 mr-1.5 mt-0.5 text-primary-500 flex-shrink-0" />
                  {{ currentBackendHint }}
                </p>
              </div>

              <div v-if="isHttpClientBackend" class="col-span-1 md:col-span-2 animate-fade-in">
                <label class="block text-sm font-medium text-gray-700 mb-1.5">{{ $t('task.serverUrl') }}</label>
                <div class="relative">
                  <input
                    v-model="config.server_url"
                    type="text"
                    :placeholder="$t('task.serverUrlPlaceholder')"
                    class="w-full pl-9 pr-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  />
                  <Globe class="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                </div>
                <p class="mt-1 text-xs text-gray-500">{{ $t('task.serverUrlHint') }}</p>
              </div>

              <div v-if="showLanguageOption" class="col-span-1">
                <label class="block text-sm font-medium text-gray-700 mb-1.5">{{ $t('task.language') }}</label>
                <select v-model="config.lang" class="w-full px-3 py-2.5 bg-white border border-gray-300 rounded-lg text-sm">
                   <option v-for="langOption in availableLanguages" :key="langOption.value" :value="langOption.value">
                     {{ langOption.label }}
                   </option>
                </select>
              </div>

              <div v-if="isMinerUBackend" class="col-span-1">
                <label class="block text-sm font-medium text-gray-700 mb-1.5">{{ $t('task.parseMethod') }}</label>
                <select v-model="config.method" class="w-full px-3 py-2.5 bg-white border border-gray-300 rounded-lg text-sm">
                   <option value="auto">{{ $t('task.methodAuto') }}</option>
                   <option value="ocr">{{ $t('task.methodOcr') }}</option>
                   <option value="txt">{{ $t('task.methodTxt') }}</option>
                </select>
              </div>

              <div v-else-if="showLanguageOption" class="col-span-1">
                <label class="block text-sm font-medium text-gray-700 mb-1.5">{{ $t('task.priorityLabel') }}</label>
                <input v-model.number="config.priority" type="number" min="0" max="100" class="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm" />
              </div>
            </div>

            <div v-if="isMinerUBackend" class="pt-4 border-t border-gray-100">
              <h3 class="text-sm font-bold text-gray-800 mb-3 flex items-center">
                <ScanText class="w-4 h-4 mr-2 text-primary-600"/> {{ $t('task.recognitionControl') }}
              </h3>

              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="border border-gray-200 rounded-lg p-3 hover:bg-gray-50 transition-colors">
                  <label class="flex items-center cursor-pointer mb-1">
                    <input v-model="config.table_enable" type="checkbox" class="w-4 h-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500" />
                    <span class="ml-2 text-sm font-medium text-gray-900">{{ $t('task.enableTableRecognition') }}</span>
                  </label>
                  <p class="text-xs text-gray-500 pl-6">{{ $t('task.tableRecognitionDisabledHint') }}</p>
                </div>

                <div class="border border-gray-200 rounded-lg p-3 hover:bg-gray-50 transition-colors">
                  <label class="flex items-center cursor-pointer mb-1">
                    <input v-model="config.formula_enable" type="checkbox" class="w-4 h-4 text-primary-600 rounded border-gray-300 focus:ring-primary-500" />
                    <span class="ml-2 text-sm font-medium text-gray-900">{{ formulaLabel }}</span>
                  </label>
                  <p class="text-xs text-gray-500 pl-6">{{ formulaDescription }}</p>
                </div>
              </div>

              <div v-if="config.method !== 'auto'" class="mt-2 text-xs text-orange-600 bg-orange-50 p-2 rounded border border-orange-100 flex items-start">
                 <AlertCircle class="w-3.5 h-3.5 mr-1.5 mt-0.5 flex-shrink-0" />
                 <span>{{ $t('task.methodHint') }}</span>
              </div>
            </div>

            <div class="bg-gray-50 rounded-lg p-1 border border-gray-200">
              <button @click="showAdvanced = !showAdvanced" class="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-100 transition-colors rounded-lg group">
                <div class="flex items-center text-sm font-medium text-gray-700">
                  <Sliders class="w-4 h-4 mr-2 text-gray-500 group-hover:text-primary-600" />
                  {{ $t('task.advancedSettings') }} <span class="ml-2 text-xs text-gray-400 font-normal">{{ $t('task.advancedSettingsHint') }}</span>
                </div>
                <component :is="showAdvanced ? ChevronUp : ChevronDown" class="w-4 h-4 text-gray-400" />
              </button>

              <div v-show="showAdvanced" class="px-4 pb-4 pt-2 space-y-5 animate-fade-in-down">
                <div v-if="isMinerUBackend">
                  <label class="block text-xs font-bold text-gray-600 uppercase tracking-wide mb-2">{{ $t('task.pageRange') }}</label>
                  <div class="flex items-center space-x-3 bg-white p-3 rounded border border-gray-200">
                    <div class="flex items-center space-x-2 flex-1">
                      <span class="text-xs text-gray-500">Start:</span>
                      <input v-model.number="config.start_page" type="number" min="0" class="form-input-sm w-full" placeholder="0" />
                    </div>
                    <span class="text-gray-300">|</span>
                    <div class="flex items-center space-x-2 flex-1">
                      <span class="text-xs text-gray-500">End:</span>
                      <input v-model.number="config.end_page" type="number" min="0" class="form-input-sm w-full" placeholder="Auto" />
                    </div>
                  </div>
                  <p class="mt-1 text-[10px] text-gray-400">{{ $t('task.pageRangeHint') }}</p>
                </div>

                <div v-if="['pipeline', 'auto'].includes(config.backend)">
                   <label class="block text-xs font-bold text-gray-600 uppercase tracking-wide mb-2">{{ $t('task.preprocessing') }}</label>
                   <div class="grid grid-cols-1 gap-3">
                      <div class="border border-gray-200 rounded p-3 bg-white">
                        <label class="flex items-center cursor-pointer mb-2">
                          <input v-model="config.remove_watermark" type="checkbox" class="form-checkbox text-purple-600 rounded border-gray-300 h-4 w-4" />
                          <span class="ml-2 text-sm font-medium text-gray-800">{{ $t('task.enableWatermarkRemoval') }}</span>
                        </label>
                        <div v-if="config.remove_watermark" class="pl-6 pt-1 space-y-2 animate-fade-in">
                           <div class="flex items-center justify-between text-xs text-gray-500">
                             <span>{{ $t('task.watermarkConfidence') }}: <span class="font-mono text-purple-600">{{ config.watermark_conf_threshold }}</span></span>
                           </div>
                           <input v-model.number="config.watermark_conf_threshold" type="range" min="0.1" max="0.9" step="0.05" class="w-full h-1.5 bg-gray-100 rounded-lg appearance-none cursor-pointer accent-purple-600" />
                        </div>
                      </div>

                   </div>
                </div>

                <div v-if="config.backend === 'video' || config.backend === 'sensevoice'">
                   <label class="block text-xs font-bold text-blue-600 uppercase tracking-wide mb-2">{{ $t('task.mediaParams') }}</label>
                   <div class="bg-blue-50 border border-blue-100 rounded p-3 space-y-2">
                      <div v-if="config.backend === 'video'">
                         <label class="flex items-center cursor-pointer"><input v-model="config.keep_audio" type="checkbox" class="mr-2 rounded text-blue-600"/> <span class="text-sm">{{ $t('task.keepAudioFile') }}</span></label>
                         <label class="flex items-center cursor-pointer mt-2"><input v-model="config.enable_keyframe_ocr" type="checkbox" class="mr-2 rounded text-blue-600"/> <span class="text-sm">{{ $t('task.enableKeyframeOCR') }}</span></label>
                      </div>
                      <div v-if="config.backend === 'sensevoice'">
                         <label class="flex items-center cursor-pointer"><input v-model="config.enable_speaker_diarization" type="checkbox" class="mr-2 rounded text-blue-600"/> <span class="text-sm">{{ $t('task.enableSpeakerDiarization') }}</span></label>
                      </div>
                   </div>
                </div>

                <div v-if="isMinerUBackend">
                  <div class="pt-2 border-t border-dashed border-gray-200 mt-2">
                    <label class="block text-xs font-bold text-gray-400 uppercase tracking-wide mb-2">{{ $t('task.outputSettings') }}</label>
                    <div class="grid grid-cols-2 gap-3 bg-white p-3 rounded border border-gray-200">
                       <label class="flex items-center cursor-pointer text-xs text-gray-600 hover:text-gray-900">
                          <input v-model="config.draw_layout_bbox" type="checkbox" class="mr-2 rounded border-gray-300" />
                          {{ $t('task.drawLayout') }}
                       </label>
                       <label class="flex items-center cursor-pointer text-xs text-gray-600 hover:text-gray-900">
                          <input v-model="config.draw_span_bbox" type="checkbox" class="mr-2 rounded border-gray-300" />
                          {{ $t('task.drawSpan') }}
                       </label>
                       <label class="flex items-center cursor-pointer text-xs text-gray-600 hover:text-gray-900">
                          <input v-model="config.dump_markdown" type="checkbox" class="mr-2 rounded border-gray-300" />
                          {{ $t('task.dumpMarkdown') }}
                       </label>
                       <label class="flex items-center cursor-pointer text-xs text-gray-600 hover:text-gray-900">
                          <input v-model="config.dump_middle_json" type="checkbox" class="mr-2 rounded border-gray-300" />
                          {{ $t('task.dumpMiddleJson') }}
                       </label>
                       <label class="flex items-center cursor-pointer text-xs text-gray-600 hover:text-gray-900">
                          <input v-model="config.dump_model_output" type="checkbox" class="mr-2 rounded border-gray-300" />
                          {{ $t('task.dumpModelOutput') }}
                       </label>
                       <label class="flex items-center cursor-pointer text-xs text-gray-600 hover:text-gray-900">
                          <input v-model="config.dump_content_list" type="checkbox" class="mr-2 rounded border-gray-300" />
                          {{ $t('task.dumpContentList') }}
                       </label>
                       <label class="flex items-center cursor-pointer text-xs text-gray-600 hover:text-gray-900">
                          <input v-model="config.dump_orig_pdf" type="checkbox" class="mr-2 rounded border-gray-300" />
                          {{ $t('task.dumpOrigPdf') }}
                       </label>
                    </div>
                  </div>
                </div>

              </div>
            </div>

          </div>
        </div>

        <div v-if="errorMessage" class="mt-4 rounded-lg bg-red-50 border border-red-200 p-4 animate-fade-in flex items-start shadow-sm">
          <AlertCircle class="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <div class="ml-3 flex-1">
            <h3 class="text-sm font-medium text-red-800">{{ $t('common.error') }}</h3>
            <p class="mt-1 text-sm text-red-700">{{ errorMessage }}</p>
          </div>
          <button @click="errorMessage = ''" class="ml-auto -mr-1 -mt-1 p-1 text-red-600 hover:text-red-800 rounded-full hover:bg-red-100 transition-colors">
            <X class="w-4 h-4" />
          </button>
        </div>

        <div v-if="submitProgress.length > 0" class="mt-6 card overflow-hidden animate-fade-in shadow-sm">
          <div class="bg-gray-50 px-4 py-3 border-b border-gray-100 flex justify-between items-center">
            <h3 class="text-sm font-semibold text-gray-900">{{ $t('common.progress') }}</h3>
            <span class="text-xs text-gray-500">{{ submitProgress.filter(p => p.success).length }} / {{ submitProgress.length }} {{ $t('task.completedCount') }}</span>
          </div>
          <div class="max-h-60 overflow-y-auto divide-y divide-gray-100 custom-scrollbar">
            <div
              v-for="(progress, index) in submitProgress"
              :key="index"
              class="flex items-center justify-between p-3 px-4 hover:bg-gray-50 transition-colors"
            >
              <div class="flex items-center flex-1 min-w-0">
                <FileText :class="['w-4 h-4 mr-3 flex-shrink-0', progress.success ? 'text-green-500' : progress.error ? 'text-red-500' : 'text-gray-400']" />
                <div class="truncate">
                   <p class="text-sm text-gray-700 truncate font-medium">{{ progress.fileName }}</p>
                   <p v-if="progress.taskId" class="text-[10px] text-gray-400 font-mono tracking-tight">{{ progress.taskId }}</p>
                   <p v-if="progress.errorMsg" class="text-[10px] text-red-500 truncate">{{ progress.errorMsg }}</p>
                </div>
              </div>
              <div class="flex items-center ml-3">
                <CheckCircle v-if="progress.success" class="w-5 h-5 text-green-500" />
                <XCircle v-else-if="progress.error" class="w-5 h-5 text-red-500" />
                <Loader v-else class="w-5 h-5 text-primary-500 animate-spin" />
              </div>
            </div>
          </div>

          <div v-if="!submitting" class="p-3 bg-gray-50 border-t border-gray-100 flex justify-end space-x-3">
            <button @click="resetForm" class="btn btn-secondary btn-sm text-xs">
              {{ $t('common.continue') }} {{ $t('task.continueClear') }}
            </button>
            <router-link to="/tasks" class="btn btn-primary btn-sm text-xs flex items-center">
              {{ $t('task.viewTaskList') }} <ArrowRight class="w-3 h-3 ml-1"/>
            </router-link>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useTaskStore } from '@/stores'
import FileUploader from '@/components/FileUploader.vue'
import {
  Upload, Loader, AlertCircle, X, FileText, CheckCircle, XCircle,
  Settings, ChevronDown, ChevronUp, Info, RotateCcw, ArrowRight,
  ScanText, Send, Sliders, Globe
} from 'lucide-vue-next'
import type { Backend, Language, ParseMethod } from '@/api/types'

const { t } = useI18n()
const router = useRouter()
const taskStore = useTaskStore()

const fileUploader = ref<InstanceType<typeof FileUploader>>()
const files = ref<File[]>([])
const submitting = ref(false)
const errorMessage = ref('')
const showAdvanced = ref(false)
const currentPreset = ref('default')

interface SubmitProgress { fileName: string; success: boolean; error: boolean; taskId?: string; errorMsg?: string }
const submitProgress = ref<SubmitProgress[]>([])

// 预设配置
const presets = computed(() => [
  { id: 'default', name: t('task.presetGeneral'), desc: t('task.presetGeneralDesc'), icon: '📄', config: { backend: 'pipeline', method: 'auto', formula_enable: true, table_enable: true } },
  { id: 'academic', name: t('task.presetAcademic'), desc: t('task.presetAcademicDesc'), icon: '🎓', config: { backend: 'hybrid-auto-engine', method: 'auto', formula_enable: true, table_enable: true } },
  { id: 'scanned', name: t('task.presetScanned'), desc: t('task.presetScannedDesc'), icon: '🖨️', config: { backend: 'hybrid-auto-engine', method: 'ocr', formula_enable: false, table_enable: true } },
  { id: 'complex', name: t('task.presetComplex'), desc: t('task.presetComplexDesc'), icon: '📊', config: { backend: 'vlm-auto-engine', method: 'auto', formula_enable: true, table_enable: true } },
])

const defaultConfig = {
  backend: 'auto' as Backend,
  lang: 'auto' as Language,
  method: 'auto' as ParseMethod,
  formula_enable: true,
  table_enable: true,
  priority: 0,
  start_page: undefined as number | undefined,
  end_page: undefined as number | undefined,

  // 预处理
  remove_watermark: false,
  watermark_conf_threshold: 0.35,
  watermark_dilation: 10,

  // 音视频
  keep_audio: false,
  enable_keyframe_ocr: false,
  enable_speaker_diarization: false,

  // 远程服务
  server_url: '',

  // Mineru Debug Options (Default: True as per source code)
  draw_layout_bbox: true,
  draw_span_bbox: true,
  dump_markdown: true,
  dump_middle_json: true,
  dump_model_output: true,
  dump_content_list: true,
  dump_orig_pdf: true
}

const config = reactive({ ...defaultConfig })

// 预设应用
function applyPreset(preset: any) {
  currentPreset.value = preset.id
  Object.assign(config, preset.config)
  if (preset.id === 'scanned') config.remove_watermark = true
}

// 后端分类
const mineruBackends = ['pipeline', 'vlm-auto-engine', 'hybrid-auto-engine', 'vlm-http-client', 'hybrid-http-client']
const isMinerUBackend = computed(() => mineruBackends.includes(config.backend))
const isHttpClientBackend = computed(() => ['vlm-http-client', 'hybrid-http-client'].includes(config.backend))

const showLanguageOption = computed(() => isMinerUBackend.value || ['sensevoice', 'auto'].includes(config.backend))

// 动态 Hint
const currentBackendHint = computed(() => {
  const map: Record<string, string> = {
    'auto': t('task.backendAutoHint'),
    'pipeline': t('task.backendPipelineHint'),
    'vlm-auto-engine': t('task.backendVLMAutoHint'),
    'hybrid-auto-engine': t('task.backendHybridAutoHint'),
    'vlm-http-client': t('task.backendVlmHttpClientHint'),
    'hybrid-http-client': t('task.backendHybridHttpClientHint'),
    'sensevoice': t('task.backendSenseVoiceHint'),
    'video': t('task.backendVideoHint'),
    'fasta': t('task.backendFastaHint'),
    'genbank': t('task.backendGenBankHint')
  }
  return map[config.backend] || ''
})

const formulaLabel = computed(() => config.backend.includes('vlm') ? t('task.enableFormulaInterline') : (config.backend.includes('hybrid') ? t('task.enableFormulaInline') : t('task.enableFormulaRecognition')))
const formulaDescription = computed(() => config.backend.includes('vlm') ? t('task.formulaDisabledHintInterline') : (config.backend.includes('hybrid') ? t('task.formulaDisabledHintInline') : t('task.formulaDisabledHintNormal')))

// 完整语言列表
const availableLanguages = computed(() => {
  const commonLangs = [
    { value: 'auto', label: t('task.langAuto') },
    { value: 'ch', label: t('task.langChinese') },
    { value: 'en', label: t('task.langEnglish') }
  ]

  if (config.backend.includes('vlm')) {
    return [
       { value: 'ch', label: t('task.langChinese') },
       { value: 'en', label: t('task.langEnglish') }
    ]
  }

  if (isMinerUBackend.value) {
    return [
      ...commonLangs,
      { value: 'korean', label: t('task.langKorean') },
      { value: 'japan', label: t('task.langJapanese') },
      { value: 'chinese_cht', label: t('task.langTraditional') },
      { value: 'ch_server', label: t('task.langChineseServer') },
      { value: 'ch_lite', label: t('task.langChineseLite') },
      { value: 'th', label: t('task.langThai') },
      { value: 'vi', label: t('task.langVietnamese') },
      { value: 'ru', label: t('task.langRussian') },
      { value: 'ar', label: t('task.langArabic') },
      { value: 'fr', label: t('task.langFrench') },
      { value: 'de', label: t('task.langGerman') },
      { value: 'ta', label: t('task.langTamil') },
      { value: 'te', label: t('task.langTelugu') },
      { value: 'ka', label: t('task.langKannada') },
      { value: 'el', label: t('task.langGreek') },
      { value: 'latin', label: t('task.langLatin') },
      { value: 'cyrillic', label: t('task.langCyrillic') },
      { value: 'devanagari', label: t('task.langDevanagari') }
    ]
  }

  return commonLangs
})

function onFilesChange(newFiles: File[]) { files.value = newFiles }

function onBackendChange() {
  currentPreset.value = 'custom';
  if (config.backend.includes('vlm')) {
     if (!['ch', 'en'].includes(config.lang)) {
        config.lang = 'ch'
     }
  }
}

onMounted(() => {
  const saved = localStorage.getItem('task_submit_config')
  if (saved) { try { const p = JSON.parse(saved); Object.assign(config, p); } catch(e){} }
})

watch(() => config, () => { localStorage.setItem('task_submit_config', JSON.stringify(config)) }, { deep: true })

function resetConfig() { Object.assign(config, defaultConfig); localStorage.removeItem('task_submit_config'); currentPreset.value = 'default' }

function resetForm() {
    files.value = [];
    if (fileUploader.value) {
       // logic to clear uploader if exposed
    }
    submitProgress.value = [];
    submitting.value = false;
    errorMessage.value = '';
}

async function submitTasks() {
  if (files.value.length === 0) { errorMessage.value = t('task.pleaseSelectFile'); return }

  if (config.start_page !== undefined && config.end_page !== undefined && config.end_page !== -1) {
    if (config.end_page < config.start_page) {
      errorMessage.value = t('task.pageError')
      showAdvanced.value = true
      return
    }
  }

  if (isHttpClientBackend.value && !config.server_url) {
    errorMessage.value = "请填写远程服务器地址 (Server URL)"
    return
  }

  submitting.value = true; errorMessage.value = ''
  submitProgress.value = files.value.map(f => ({ fileName: f.name, success: false, error: false }))

  for (let i = 0; i < files.value.length; i++) {
    try {
      const submitConfig = { ...config }
      if (submitConfig.end_page === undefined) delete (submitConfig as any).end_page

      const response = await taskStore.submitTask({ file: files.value[i], ...submitConfig })
      submitProgress.value[i].success = true; submitProgress.value[i].taskId = response.task_id
    } catch (err: any) {
      submitProgress.value[i].error = true; submitProgress.value[i].errorMsg = err.message
    }
  }
  submitting.value = false
  if (submitProgress.value.every(p => p.success) && files.value.length === 1) {
    setTimeout(() => { router.push(`/tasks/${submitProgress.value[0].taskId}`) }, 500)
  }
}
</script>

<style scoped>
.form-input-sm { @apply px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-primary-500 transition-colors; }
.form-checkbox { @apply rounded border-gray-300 focus:ring-primary-500 cursor-pointer; }
.animate-fade-in { animation: fadeIn 0.3s ease-out; }
.animate-fade-in-down { animation: fadeInDown 0.2s ease-out; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes fadeInDown { from { opacity: 0; transform: translateY(-5px); } to { opacity: 1; transform: translateY(0); } }
.custom-scrollbar::-webkit-scrollbar { width: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: #f8f9fa; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
</style>
