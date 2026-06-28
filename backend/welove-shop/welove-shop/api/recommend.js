import request from '../utils/request'

export function feedback(id, feedbackValue) {
  return request({ url: '/api/recommend/feedback', method: 'POST', data: { id, feedback: feedbackValue }, header: { 'content-type': 'application/x-www-form-urlencoded' } })
}
export function recordBrowse(data) {
  return request({ url: '/api/recommend/browse', method: 'POST', data })
}
export function addFavorite(productId) {
  return request({ url: '/api/recommend/favorite/add', method: 'POST', data: { productId }, header: { 'content-type': 'application/x-www-form-urlencoded' } })
}
export function removeFavorite(productId) {
  return request({ url: '/api/recommend/favorite/remove', method: 'POST', data: { productId }, header: { 'content-type': 'application/x-www-form-urlencoded' } })
}
export function getFavoriteList() {
  return request({ url: '/api/recommend/favorite/list', method: 'GET' })
}
export function getBrowseHistory() {
  return request({ url: '/api/recommend/browse/history', method: 'GET' })
}
export function deleteBrowseHistory(id) {
  return request({ url: `/api/recommend/browse/history/${id}`, method: 'DELETE' })
}
