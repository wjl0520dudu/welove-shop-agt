import userStore from '../store/user'

const LOGIN_URL = '/pages/login/login'
const PROFILE_TAB = '/pages/profile/profile'
let loginNavigating = false

export function isLoggedIn() {
  userStore.restore()
  return userStore.isLoggedIn()
}

export function toLogin(redirect) {
  if (loginNavigating) return
  loginNavigating = true
  const query = redirect ? `?redirect=${encodeURIComponent(redirect)}` : ''
  uni.navigateTo({
    url: `${LOGIN_URL}${query}`,
    complete() {
      setTimeout(() => {
        loginNavigating = false
      }, 300)
    }
  })
}

export function requireLogin(redirect) {
  if (isLoggedIn()) return true
  toLogin(redirect)
  return false
}

export function requireLoginFromProtectedTab(tabPath) {
  if (isLoggedIn()) return true

  uni.switchTab({
    url: PROFILE_TAB,
    success() {
      setTimeout(() => toLogin(tabPath), 50)
    }
  })
  return false
}