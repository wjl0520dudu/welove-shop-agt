import { login as loginApi, getProfile } from '../api/auth'
import { clearAuth, getRefreshToken, getStoredUser, getToken, setRefreshToken, setStoredUser, setToken } from '../utils/auth'

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
  state.user = data.user || null
  setToken(state.token)
  setRefreshToken(state.refreshToken)
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
    applyAuth(data)
    return data
  },
  async loadProfile() {
    const user = await getProfile()
    state.user = user
    setStoredUser(user)
    return user
  },
  logout() {
    state.token = ''
    state.refreshToken = ''
    state.user = null
    clearAuth()
  }
}
