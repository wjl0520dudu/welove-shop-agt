import request from '../utils/request'

export function createConversation(title) {
  return request({ url: '/api/chat/conversations', method: 'POST', data: { title }, header: { 'content-type': 'application/x-www-form-urlencoded' } })
}
export function getConversations() {
  return request({ url: '/api/chat/conversations', method: 'GET' })
}
export function getMessages(conversationId) {
  return request({ url: '/api/chat/messages', method: 'GET', data: { conversationId } })
}
export function sendMessage(data) {
  return request({ url: '/api/chat/messages', method: 'POST', data })
}
export function saveMessage(data) {
  return request({ url: '/api/chat/messages/save', method: 'POST', data })
}
export function deleteConversation(id) {
  return request({ url: `/api/chat/conversations/${id}`, method: 'DELETE' })
}
export function updateConversation(id, data) {
  return request({ url: `/api/chat/conversations/${id}`, method: 'PUT', data })
}
