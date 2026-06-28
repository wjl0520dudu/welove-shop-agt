import request from '../utils/request'

export function getAddressList() {
  return request({ url: '/api/address/list', method: 'GET' })
}
export function addAddress(data) {
  return request({ url: '/api/address/add', method: 'POST', data })
}
export function updateAddress(data) {
  return request({ url: '/api/address/update', method: 'PUT', data })
}
export function deleteAddress(id) {
  return request({ url: '/api/address/delete', method: 'DELETE', data: { id } })
}
export function setDefaultAddress(id) {
  return request({ url: '/api/address/setDefault', method: 'PUT', data: { id }, header: { 'content-type': 'application/x-www-form-urlencoded' } })
}
