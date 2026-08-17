/**
 * 全局环境配置 —— H5 单点配置
 *
 * 开发期 API 走 Vite 代理（/api → 网关 :8080）；生产由 nginx 同源反代，
 * 故 API_BASE_URL 留空即可在两种环境下同源命中 /api。
 * 未来若需跨域直连网关，只改这一处。
 */
export const API_BASE_URL = ''

const RUNTIME_CONFIG = typeof window !== 'undefined' ? (window.__WLS_RUNTIME_CONFIG__ || {}) : {}

function readEnabled(value, fallback = false) {
  if (value === undefined || value === null || value === '') return fallback
  return ['true', '1', 'yes', 'on'].includes(String(value).trim().toLowerCase())
}

/** 演示环境默认只开放体验登录，真实短信接入后可由 runtime-config.js 覆盖。 */
export const SMS_LOGIN_ENABLED = readEnabled(
  RUNTIME_CONFIG.SMS_LOGIN_ENABLED,
  readEnabled(
    typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_SMS_LOGIN_ENABLED,
    false
  )
)

/**
 * 商品图片主机(单一可配置项,前端所有图片 URL 拼接的唯一出处)
 *
 * 行为:
 *   - 非空时:相对路径走 `<IMAGE_BASE_URL> + 路径`;已经是 http(s):// 的绝对 URL 直接透传。
 *   - 空字符串 '':相对路径保持相对(由 Vite / nginx 代理),绝对 URL 直接透传。
 *
 * 部署期配置(取其一即可,优先级 uni-app 环境变量 > 此处默认值):
 *   - uni-app 环境变量:    VITE_IMAGE_BASE_URL=https://cdn.example.com
 *   - 构建时手动改默认值:  下方的 fallback
 *
 * 历史背景:接阿里云 OSS 后,后端 (chat-service / 后续 product-service) 会直接返回
 * 完整 https://<bucket>.<endpoint>/... 形式的 imageUrl,前端无须再拼主机;
 * 此时把 IMAGE_BASE_URL 留空即可,绝对 URL 在 buildImageUrl 中原样返回。
 *
 * 之所以还要保留这个变量:商品列表里仍有相对路径形态的图片(如 "/img/p1.jpg"),
 * 这些历史数据走本变量拼接;后续所有新图片应直接由后端返回完整 URL,本变量逐步废弃。
 */
export const IMAGE_BASE_URL =
  RUNTIME_CONFIG.IMAGE_BASE_URL ||
  // 1. uni-app 编译期注入的环境变量(推荐 — 不同构建产物走不同配置)
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_IMAGE_BASE_URL) ||
  // 2. 兜底默认值:开发期指向 OSS 图片主机
  'https://liangwenjun.oss-cn-hangzhou.aliyuncs.com'
