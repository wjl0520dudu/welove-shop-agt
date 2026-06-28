const BASE_URL = 'http://localhost:8888'

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

export function buildImageUrl(url) {
  if (!url) return ''
  const raw = String(url).trim()
  if (!raw) return ''
  if (/^data:image\//.test(raw)) return raw
  if (/^https?:\/\//.test(raw)) return encodePath(raw.replace('localhost:8080', 'localhost:8888'))
  const path = raw.startsWith('/') ? raw : `/product-images/${raw}`
  return encodePath(`${BASE_URL}${path}`)
}

export function pickProductImage(product = {}) {
  return product.imageUrl || product.productImage || product.cover || product.product?.imageUrl || product.product?.productImage || ''
}
