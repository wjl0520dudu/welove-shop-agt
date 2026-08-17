import { login as loginApi, getProfile } from '../api/auth'
import { clearAuth, getRefreshToken, getStoredUser, getToken, setRefreshToken, setStoredUser, setToken } from '../utils/auth'
import chatStore from './chat'
import cartStore from './cart'

const state = {
  token: '',
  refreshToken: '',
  user: null
}

function readToken(data = {}) {
  return data.token || data.accessToken || ''
}

function applyAuth(data = {}) {
  state.token = readToken(data)
  state.refreshToken = data.refreshToken || ''
  setToken(state.token)
  setRefreshToken(state.refreshToken)
  setCurrentUser(data.user || null)
}

function setCurrentUser(user) {
  state.user = user || null
  setStoredUser(state.user)
}

export default {
  state,
  restore() {
    state.token = getToken()
    state.refreshToken = getRefreshToken()
    state.user = getStoredUser()
  },
  isLoggedIn() {
    return Boolean(state.token || getToken())
  },
  async login(payload) {
    const data = await loginApi(payload)
    cartStore.beginSession()
    applyAuth(data)
    cartStore.refreshAndSyncBadge().catch(() => {})
    return data
  },
  /**
   * 测试登录:服务端已返回完整 { token, refreshToken, user },直接落本地即可。
   * 与 login() 区别:不调用 loginApi,不走短信验证码。
   */
  async handleTestLogin(data) {
    cartStore.beginSession()
    applyAuth(data)
    cartStore.refreshAndSyncBadge().catch(() => {})
    return data
  },
  async loadProfile() {
    const user = await getProfile()
    setCurrentUser(user)
    return user
  },
  setUser(user) {
    setCurrentUser(user)
    return state.user
  },
  needsProfileSetup(user = state.user) {
    const profile = user || {}
    const noGender = profile.gender === null || profile.gender === undefined || profile.gender === 0
    const noTags = !Array.isArray(profile.preferenceTags) || profile.preferenceTags.length === 0
    return noGender && noTags
  },
  logout() {
    state.token = ''
    state.refreshToken = ''
    state.user = null
    clearAuth()
    chatStore.reset()
    cartStore.reset()
  }
}
