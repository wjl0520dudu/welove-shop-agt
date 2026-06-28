const BASE_URL = 'http://localhost:8888'
const FILE_NAME_PATTERN = /^[^/]+\.(png|jpe?g|webp|gif|bmp|svg)$/i

function encodePath(url) {
  return url.split('/').map((segment) => {
    if (!segment || segment.includes(':')) return segment
    try {
      return encodeURIComponent(decodeURIComponent(segment)).replace(/%2F/g, '/')
    } catch (error) {
      return encodeURIComponent(segment).replace(/%2F/g, '/')
    }
  }).join('/')
}

function normalizeAbsoluteUrl(url) {
  return url
    .replace('localhost:8080', 'localhost:8888')
    .replace('127.0.0.1:8080', '127.0.0.1:8888')
}

export function buildImageUrl(url) {
  if (!url) return ''
  const raw = String(url).trim()
  if (!raw) return ''
  if (/^data:image\//.test(raw) || /^blob:/.test(raw)) return raw
  if (/^https?:\/\//.test(raw)) return encodePath(normalizeAbsoluteUrl(raw))

  const path = raw.startsWith('/')
    ? raw
    : FILE_NAME_PATTERN.test(raw)
      ? `/product-images/${raw}`
      : `/${raw}`

  return encodePath(`${BASE_URL}${path}`)
}

export function pickProductImage(product = {}) {
  return product.imageUrl || product.productImage || product.cover || product.product?.imageUrl || product.product?.productImage || ''
}
