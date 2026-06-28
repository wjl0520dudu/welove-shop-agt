const TOKEN_KEY = 'shopagent_token'
const REFRESH_TOKEN_KEY = 'shopagent_refresh_token'
const USER_KEY = 'shopagent_user'

export function getToken() {
  return uni.getStorageSync(TOKEN_KEY) || ''
}

export function setToken(token) {
  uni.setStorageSync(TOKEN_KEY, token || '')
}

export function getRefreshToken() {
  return uni.getStorageSync(REFRESH_TOKEN_KEY) || ''
}

export function setRefreshToken(token) {
  uni.setStorageSync(REFRESH_TOKEN_KEY, token || '')
}

export function getStoredUser() {
  return uni.getStorageSync(USER_KEY) || null
}

export function setStoredUser(user) {
  uni.setStorageSync(USER_KEY, user || null)
}

export function clearAuth() {
  uni.removeStorageSync(TOKEN_KEY)
  uni.removeStorageSync(REFRESH_TOKEN_KEY)
  uni.removeStorageSync(USER_KEY)
}

export function isLoggedIn() {
  return Boolean(getToken())
}
