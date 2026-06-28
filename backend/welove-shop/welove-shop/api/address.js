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
  return request({ url: `/api/address/delete?id=${encodeURIComponent(id)}`, method: 'DELETE' })
}
export function setDefaultAddress(id) {
  return request({ url: `/api/address/setDefault?id=${encodeURIComponent(id)}`, method: 'PUT' })
}
