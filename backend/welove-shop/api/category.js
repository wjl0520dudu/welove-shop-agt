import request from '../utils/request'

export function getCategories() {
  return request({ url: '/api/category/list', method: 'GET' })
}

export function getCategoryDetail(id) {
  return request({ url: `/api/category/${id}`, method: 'GET' })
}
