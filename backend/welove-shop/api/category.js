import request from '../utils/request'

export function getCategories() {
  return request({ url: '/api/category/list', method: 'GET' })
}
