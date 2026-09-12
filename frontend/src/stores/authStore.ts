/**
 * 认证状态管理
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import * as authApi from '@/api/authApi'
import type { User, LoginRequest, RegisterRequest } from '@/api/types'
import { showToast } from '@/utils/toast'

export const useAuthStore = defineStore('auth', () => {
  // State
  const token = ref<string | null>(localStorage.getItem('auth_token'))
  const user = ref<User | null>(null)
  const loading = ref(false)

  // Getters
  const isAuthenticated = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isManager = computed(() => user.value?.role === 'manager' || user.value?.role === 'admin')

  /**
   * 登录
   */
  async function login(credentials: LoginRequest) {
    try {
      loading.value = true
      const response = await authApi.login(credentials)

      // 保存 Token
      token.value = response.access_token
      localStorage.setItem('auth_token', response.access_token)

      // 获取用户信息
      await fetchCurrentUser()

      showToast({ message: '登录成功', type: 'success' })
      return true
    } catch (error: any) {
      console.error('Login error:', error)

      // 处理不同类型的错误
      let message = '登录失败，请稍后重试'

      if (error.response) {
        // 服务器返回错误响应
        const status = error.response.status
        const detail = error.response.data?.detail

        if (status === 401) {
          message = '用户名或密码错误'
        } else if (status === 403) {
          message = detail || '账户已被禁用'
        } else if (status === 500) {
          message = '服务器内部错误，请联系管理员'
          // 在控制台显示详细错误信息便于调试
          console.error('Server error details:', error.response.data)
        } else if (detail) {
          message = detail
        }
      } else if (error.request) {
        // 请求已发送但没有收到响应
        message = '无法连接到服务器，请检查网络连接'
      }

      showToast({ message, type: 'error' })
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 注册
   */
  async function register(userData: RegisterRequest) {
    try {
      loading.value = true
      await authApi.register(userData)
      showToast({ message: '注册成功，请登录', type: 'success' })
      return true
    } catch (error: any) {
      console.error('Register error:', error)

      // 处理不同类型的错误
      let message = '注册失败，请稍后重试'

      if (error.response) {
        const status = error.response.status
        const detail = error.response.data?.detail

        if (status === 400) {
          message = detail || '注册信息有误，请检查输入'
        } else if (status === 409) {
          message = '用户名或邮箱已存在'
        } else if (status === 500) {
          message = '服务器内部错误，请联系管理员'
          console.error('Server error details:', error.response.data)
        } else if (detail) {
          message = detail
        }
      } else if (error.request) {
        message = '无法连接到服务器，请检查网络连接'
      }

      showToast({ message, type: 'error' })
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 登出
   */
  async function logout() {
    // 先通知后端吊销 Token，失败也不阻塞本地登出
    if (token.value) {
      try {
        await authApi.logout()
      } catch (error) {
        console.error('Logout API error:', error)
      }
    }
    token.value = null
    user.value = null
    localStorage.removeItem('auth_token')
    showToast({ message: '已退出登录', type: 'info' })
  }

  /**
   * 获取当前用户信息
   */
  async function fetchCurrentUser() {
    if (!token.value) {
      return
    }

    try {
      user.value = await authApi.getCurrentUser()
    } catch (error: any) {
      console.error('Fetch user error:', error)
      // Token 可能已过期，清除登录状态
      if (error.response?.status === 401) {
        logout()
      }
    }
  }

  /**
   * 更新当前用户信息
   */
  async function updateProfile(data: Partial<User>) {
    try {
      loading.value = true
      user.value = await authApi.updateCurrentUser(data)
      showToast({ message: '信息更新成功', type: 'success' })
      return true
    } catch (error: any) {
      console.error('Update profile error:', error)
      const message = error.response?.data?.detail || '更新失败'
      showToast({ message, type: 'error' })
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 修改密码
   */
  async function changePassword(oldPassword: string, newPassword: string) {
    try {
      loading.value = true
      await authApi.changePassword({
        old_password: oldPassword,
        new_password: newPassword,
      })
      showToast({ message: '密码修改成功', type: 'success' })
      return true
    } catch (error: any) {
      console.error('Change password error:', error)

      let message = '密码修改失败'
      if (error.response) {
        const status = error.response.status
        const detail = error.response.data?.detail

        if (status === 400 && detail?.includes('Incorrect old password')) {
          message = '旧密码错误'
        } else if (status === 403 && detail?.includes('SSO users')) {
          message = 'SSO 用户不能修改密码'
        } else if (detail) {
          message = detail
        }
      } else if (error.request) {
        message = '无法连接到服务器，请检查网络连接'
      }

      showToast({ message, type: 'error' })
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * 检查权限
   */
  function hasPermission(permission: string): boolean {
    if (!user.value) return false

    // Admin 拥有所有权限
    if (user.value.role === 'admin') return true

    // Manager 权限
    const managerPermissions = [
      'task:submit',
      'task:view:all',
      'task:delete:own',
      'queue:view',
      'user:list',
      'apikey:create',
      'apikey:delete',
      'apikey:list:own',
      'system:stats',
    ]

    // User 权限
    const userPermissions = [
      'task:submit',
      'task:view:own',
      'task:delete:own',
      'queue:view',
      'apikey:create',
      'apikey:list:own',
    ]

    if (user.value.role === 'manager') {
      return managerPermissions.includes(permission)
    }

    if (user.value.role === 'user') {
      return userPermissions.includes(permission)
    }

    return false
  }

  /**
   * 初始化（页面加载时调用）
   * 幂等操作：可以安全地多次调用
   */
  async function initialize() {
    // 如果没有 token 或已经有用户信息，跳过初始化
    if (!token.value || user.value) {
      return
    }

    await fetchCurrentUser()
  }

  return {
    // State
    token,
    user,
    loading,

    // Getters
    isAuthenticated,
    isAdmin,
    isManager,

    // Actions
    login,
    register,
    logout,
    fetchCurrentUser,
    updateProfile,
    changePassword,
    hasPermission,
    initialize,
  }
})
