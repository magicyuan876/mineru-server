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

      <!-- 注册功能已关闭提示 -->
      <div v-if="!allowRegistration" class="bg-white rounded-2xl shadow-xl p-8">
        <div class="text-center">
          <svg class="mx-auto h-12 w-12 text-yellow-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <h2 class="mt-4 text-xl font-semibold text-gray-900">{{ $t('auth.registrationDisabled') }}</h2>
          <p class="mt-2 text-sm text-gray-600">{{ $t('auth.registrationDisabledMessage') }}</p>
          <div class="mt-6">
            <router-link
              to="/login"
              class="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              {{ $t('auth.goToLogin') }}
            </router-link>
          </div>
        </div>
      </div>

      <!-- 注册表单 -->
      <div v-else class="bg-white rounded-2xl shadow-xl p-8">
        <h2 class="text-2xl font-semibold text-gray-900 mb-6">{{ $t('auth.registerTitle', { systemName: systemConfig.system_name }) }}</h2>

        <form @submit.prevent="handleRegister" class="space-y-4">
          <!-- 用户名 -->
          <div>
            <label for="username" class="block text-sm font-medium text-gray-700 mb-1">
              {{ $t('auth.username') }} *
            </label>
            <input
              id="username"
              v-model="form.username"
              type="text"
              required
              pattern="[a-zA-Z0-9_-]{3,50}"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              :placeholder="$t('auth.username')"
            />
          </div>

          <!-- 邮箱 -->
          <div>
            <label for="email" class="block text-sm font-medium text-gray-700 mb-1">
              {{ $t('auth.email') }} *
            </label>
            <input
              id="email"
              v-model="form.email"
              type="email"
              required
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              :placeholder="$t('auth.email')"
            />
          </div>

          <!-- 密码 -->
          <div>
            <label for="password" class="block text-sm font-medium text-gray-700 mb-1">
              {{ $t('auth.password') }} *
            </label>
            <input
              id="password"
              v-model="form.password"
              type="password"
              required
              minlength="8"
              maxlength="100"
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              :placeholder="$t('auth.password')"
            />
          </div>

          <!-- 确认密码 -->
          <div>
            <label for="confirm_password" class="block text-sm font-medium text-gray-700 mb-1">
              {{ $t('auth.confirmPassword') }} *
            </label>
            <input
              id="confirm_password"
              v-model="confirmPassword"
              type="password"
              required
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              :placeholder="$t('auth.confirmPassword')"
            />
          </div>

          <!-- 邀请码（管理员开启邀请码注册时显示） -->
          <div v-if="systemConfig.registration_invite_required">
            <label for="invite_code" class="block text-sm font-medium text-gray-700 mb-1">
              {{ $t('auth.inviteCode') }} *
            </label>
            <input
              id="invite_code"
              v-model="form.invite_code"
              type="text"
              required
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              :placeholder="$t('auth.inviteCodePlaceholder')"
            />
          </div>

          <!-- 注册按钮 -->
          <button
            type="submit"
            :disabled="authStore.loading || (confirmPassword && confirmPassword !== form.password)"
            class="w-full bg-blue-600 text-white py-2.5 rounded-lg font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors mt-6"
          >
            <span v-if="!authStore.loading">{{ $t('auth.registerButton') }}</span>
            <span v-else class="flex items-center justify-center">
              <svg class="animate-spin h-5 w-5 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              {{ $t('common.loading') }}
            </span>
          </button>
        </form>

        <!-- 登录链接 -->
        <div class="mt-6 text-center">
          <p class="text-sm text-gray-600">
            {{ $t('auth.hasAccount') }}
            <router-link to="/login" class="text-blue-600 hover:text-blue-700 font-medium">
              {{ $t('auth.goToLogin') }}
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
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores'
import { getSystemConfig, type SystemConfig } from '@/api'

const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()

const form = reactive({
  username: '',
  email: '',
  password: '',
  full_name: '',
  invite_code: '',
})

const confirmPassword = ref('')
const allowRegistration = ref(false) // 默认不允许注册，加载配置后再放开
const systemConfig = ref<SystemConfig>({
  system_name: 'MinerU Tianshu',
  system_logo: '',
  show_github_star: true,
  allow_registration: true,
})

async function handleRegister() {
  if (confirmPassword.value !== form.password) {
    return
  }

  const success = await authStore.register(form)
  if (success) {
    // 注册成功，跳转到登录页
    router.push('/login')
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
    document.title = `${systemConfig.value.system_name} - 注册`
  } catch (error) {
    console.error('Failed to load system config:', error)
    // 失败时 fail-closed，隐藏注册表单
    allowRegistration.value = false
  }
}

onMounted(() => {
  loadSystemConfig()
})
</script>
