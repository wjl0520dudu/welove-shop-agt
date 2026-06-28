import request from '../utils/request'

export function getProductList(params = {}) {
  return request({ url: '/api/product/list', method: 'GET', data: params })
}
export function getProductDetail(id) {
  return request({ url: `/api/product/${id}`, method: 'GET' })
}
export function getProductSkus(id) {
  return request({ url: `/api/product/${id}/skus`, method: 'GET' })
}
export function getProductReviews(id, limit = 10) {
  return request({ url: `/api/product/${id}/reviews`, method: 'GET', data: { limit } })
}
export function getProductFaqs(id) {
  return request({ url: `/api/product/${id}/faqs`, method: 'GET' })
}
export function getProductImages(id) {
  return request({ url: `/api/product/${id}/images`, method: 'GET' })
}
export function searchProducts(keyword, limit = 20) {
  return request({ url: '/api/product/search', method: 'GET', data: { keyword, limit } })
}
export function getHotProducts(limit = 10) {
  return request({ url: '/api/product/hot', method: 'GET', data: { limit } })
}
export function submitReview(productId, rating, content) {
  return request({ url: `/api/product/${productId}/reviews`, method: 'POST', data: { rating, content }, header: { 'content-type': 'application/x-www-form-urlencoded' } })
}
