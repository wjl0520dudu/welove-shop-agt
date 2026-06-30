import userStore from '../store/user'

const LOGIN_URL = '/pages/login/login'
const PROFILE_TAB = '/pages/profile/profile'
const TAB_PAGES = ['/pages/chat/chat', '/pages/product-list/product-list', '/pages/cart/cart', '/pages/profile/profile']
let loginNavigating = false

export function isTabPage(url = '') {
  const path = url.split('?')[0]
  return TAB_PAGES.includes(path)
}

export function isLoggedIn() {
  userStore.restore()
  return userStore.isLoggedIn()
}

export function currentPagePath() {
  const pages = getCurrentPages()
  return pages.length ? `/${pages[pages.length - 1].route}` : ''
}

export function toLogin(redirect) {
  const current = currentPagePath()
  if (current === LOGIN_URL || current === '/pages/login-code/login-code') return
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
  toLogin(redirect || currentPagePath())
  return false
}

export function requireLoginFromProtectedTab(tabPath) {
  if (isLoggedIn()) return true

  uni.switchTab({
    url: PROFILE_TAB,
    complete() {
      setTimeout(() => toLogin(tabPath), 50)
    }
  })
  return false
}
