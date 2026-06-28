import { clearAuth, getRefreshToken, getToken, setRefreshToken, setToken } from './auth'

const BASE_URL = 'http://localhost:8888'
let refreshingPromise = null

function normalizeUrl(url) {
  if (/^https?:\/\//.test(url)) return url
  return `${BASE_URL}${url}`
}

function rawRequest(options) {
  return new Promise((resolve, reject) => {
    uni.request({
      ...options,
      url: normalizeUrl(options.url),
      success: resolve,
      fail: reject
    })
  })
}

function toFormData(data = {}) {
  return Object.keys(data)
    .filter((key) => data[key] !== undefined && data[key] !== null)
    .map((key) => `${encodeURIComponent(key)}=${encodeURIComponent(data[key])}`)
    .join('&')
}

async function refreshAccessToken() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return false

  if (!refreshingPromise) {
    refreshingPromise = rawRequest({
      url: '/api/auth/refresh',
      method: 'POST',
      header: { Authorization: `Bearer ${refreshToken}` }
    }).finally(() => {
      refreshingPromise = null
    })
  }

  const response = await refreshingPromise
  const body = response.data
  if (response.statusCode === 200 && body?.code === 200 && body.data?.token) {
    setToken(body.data.token)
    if (body.data.refreshToken) setRefreshToken(body.data.refreshToken)
    return true
  }
  return false
}

function redirectToLogin() {
  const pages = getCurrentPages()
  const current = pages.length ? `/${pages[pages.length - 1].route}` : ''
  const query = current ? `?redirect=${encodeURIComponent(current)}` : ''
  clearAuth()
  uni.navigateTo({ url: `/pages/login/login${query}` })
}

export async function request(options) {
  const token = getToken()
  const header = { ...(options.header || {}) }
  let data = options.data || {}

  if (token) header.Authorization = `Bearer ${token}`

  const contentType = header['content-type'] || header['Content-Type'] || ''
  if (contentType.includes('application/x-www-form-urlencoded')) {
    data = toFormData(data)
  }

  const response = await rawRequest({
    timeout: 30000,
    ...options,
    data,
    header
  })

  if ((response.statusCode === 401 || response.statusCode === 403) && token) {
    const refreshed = await refreshAccessToken()
    if (refreshed) return request(options)
    redirectToLogin()
    throw new Error('登录已过期，请重新登录')
  }

  const body = response.data
  if (response.statusCode < 200 || response.statusCode >= 300) {
    const message = body?.message || `请求失败：${response.statusCode}`
    uni.showToast({ title: message, icon: 'none' })
    throw new Error(message)
  }

  if (body && Object.prototype.hasOwnProperty.call(body, 'code')) {
    if (body.code === 200 || body.code === 0) return body.data
    const message = body.message || '请求失败'
    uni.showToast({ title: message, icon: 'none' })
    throw new Error(message)
  }

  return body
}

export default request