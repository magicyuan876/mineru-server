<template>
  <div class="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 px-4">
    <div class="max-w-md w-full">
      <!-- Logo 和标题 -->
      <div class="text-center mb-8">
        <!-- Logo -->
        <div v-if="systemConfig.system_logo" class="mb-4 flex justify-center">
          <img
            :src="systemConfig.system_logo"
            :alt="`${systemConfig.system_name} Logo`"
            class="h-16 object-contain"
            @error="handleLogoError"
          />
        </div>
        <h1 class="text-4xl font-bold text-gray-900 mb-2">{{ systemConfig.system_name }}</h1>
        <p class="text-gray-600">{{ $t('auth.systemSubtitle') }}</p>
      </div>

      <!-- 登录表单 -->
      <div class="bg-white rounded-2xl shadow-xl p-8">
        <h2 class="text-2xl font-semibold text-gray-900 mb-6">{{ $t('auth.loginTitle', { systemName: systemConfig.system_name }) }}</h2>

        <form @submit.prevent="handleLogin" class="space-y-4">
          <!-- 用户名 -->
          <div>
            <label for="username" class="block text-sm font-medium text-gray-700 mb-1">
              {{ $t('auth.username') }}
            </label>
            <input
              id="username"
              v-model="form.username"
              type="text"
              required
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              :placeholder="$t('auth.username')"
            />
          </div>

          <!-- 密码 -->
          <div>
            <label for="password" class="block text-sm font-medium text-gray-700 mb-1">
              {{ $t('auth.password') }}
            </label>
            <input
              id="password"
              v-model="form.password"
              type="password"
              required
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              :placeholder="$t('auth.password')"
            />
          </div>

          <!-- 登录按钮 -->
          <button
            type="submit"
            :disabled="authStore.loading"
            class="w-full bg-blue-600 text-white py-2.5 rounded-lg font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <span v-if="!authStore.loading">{{ $t('auth.loginButton') }}</span>
            <span v-else class="flex items-center justify-center">
              <svg class="animate-spin h-5 w-5 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              {{ $t('common.loading') }}
            </span>
          </button>
        </form>

        <!-- 注册链接 -->
        <div v-if="allowRegistration" class="mt-6 text-center">
          <p class="text-sm text-gray-600">
            {{ $t('auth.noAccount') }}
            <router-link to="/register" class="text-blue-600 hover:text-blue-700 font-medium">
              {{ $t('auth.goToRegister') }}
            </router-link>
          </p>
        </div>
      </div>

      <!-- 版权信息 -->
      <div class="mt-8 text-center text-sm text-gray-600">

      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores'
import { getSystemConfig, type SystemConfig } from '@/api'

const router = useRouter()
const authStore = useAuthStore()

const form = reactive({
  username: '',
  password: '',
})

const allowRegistration = ref(false) // 默认不允许注册，加载配置后再放开
const systemConfig = ref<SystemConfig>({
  system_name: 'MinerU Tianshu',
  system_logo: '',
  show_github_star: true,
  allow_registration: true,
})

async function handleLogin() {
  const success = await authStore.login(form)
  if (success) {
    // 登录成功，跳转到首页
    router.push('/')
  }
}

/**
 * Logo 加载失败处理
 */
function handleLogoError(event: Event) {
  const target = event.target as HTMLImageElement
  target.style.display = 'none'
}

/**
 * 加载系统配置
 */
async function loadSystemConfig() {
  try {
    const response = await getSystemConfig()
    systemConfig.value = response.config
    allowRegistration.value = response.config.allow_registration !== false

    // 更新页面标题
    document.title = `${systemConfig.value.system_name} - 登录`
  } catch (error) {
    console.error('Failed to load system config:', error)
    // 失败时 fail-closed，隐藏注册入口
    allowRegistration.value = false
  }
}

onMounted(() => {
  loadSystemConfig()
})
</script>
