import request from '../utils/request'
import { getToken } from '../utils/auth'
import { postEventStream } from '../utils/sse'

export function createConversation(title) {
  return request({ url: '/api/chat/chat/conversations', method: 'POST', data: { title }, header: { 'content-type': 'application/x-www-form-urlencoded' } })
}
export function getConversations() {
  return request({ url: '/api/chat/chat/conversations', method: 'GET' })
}
export function getMessages(conversationId) {
  return request({ url: '/api/chat/chat/messages', method: 'GET', data: { conversationId } })
}
export function sendMessage(data) {
  return request({ url: '/api/chat/chat/messages', method: 'POST', data })
}
export function deleteConversation(id) {
  return request({ url: `/api/chat/chat/conversations/${id}`, method: 'DELETE' })
}
export function updateConversation(id, params = {}) {
  // 后端以 @RequestParam 接收 title / isPinned，用查询串传递
  const query = Object.keys(params)
    .filter((k) => params[k] !== undefined && params[k] !== null)
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join('&')
  const suffix = query ? `?${query}` : ''
  return request({ url: `/api/chat/chat/conversations/${id}${suffix}`, method: 'PUT' })
}

/** 消息点赞/点踩反馈 */
export function feedback(messageId, feedbackType) {
  return request({ url: '/api/chat/chat/messages/feedback', method: 'POST', data: { messageId, feedbackType } })
}

/**
 * 中止流式时把已收到的半成品发到后端落库（豆包式体验）。
 * 后端 ChatServiceImpl.persistTruncatedFromClient 会写入 status='truncated' 的 assistant 消息,
 * 配合 doOnCancel 兜底,保证双保险(网络通则前端落库,网络断则后端兜底,SQL 去重避免重复)。
 *
 * @param {object} payload { conversationId, content, productCards?, confirmCard?, cartSelection?, taskType?, clientTs? }
 * @returns {Promise<number|null>} 新插入(或去重命中)的 message id
 */
export function stopStream(payload = {}) {
  return request({ url: '/api/chat/chat/messages/stop', method: 'POST', data: { ...payload, clientTs: payload.clientTs || Date.now() } })
}

/**
 * 流式发送消息（SSE）
 *
 * uni.request 无法流式，故走 fetch + ReadableStream，手动注入 Bearer。
 * 事件命名做双向兼容映射后回调给页面。
 *
 * @param {object} payload  { userId, conversationId, content, username?, isAdmin?, gender?, skinType?, preferenceTags? }
 * @param {object} cb  { onOpen, onText, onProductCards, onConfirm, onCartSelection, onRouted, onDone, onError }
 * @returns {{ promise: Promise<void>, abort: () => void }}
 */
export function streamMessage(payload, cb = {}) {
  const token = getToken()
  return postEventStream('/api/chat/chat/stream/messages', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: payload,
    onOpen: cb.onOpen,
    onEvent: (frame) => dispatchChatEvent(frame, cb)
  })
}

/**
 * 兼容旧调用的图文流式函数。实际统一调用 streamMessage，imageUrl 为可选字段。
 *
 * @param {object} payload  同 streamMessage；带 imageUrl 时 content 可为空（纯图搜索）
 * @param {object} cb       同 streamMessage
 */
export function streamMultimodalMessage(payload, cb = {}) {
  return streamMessage(payload, cb)
}

/**
 * 上传聊天图片到 chat-service / OSS。走 uni.uploadFile,携带 Bearer。
 *
 * 后端会做 MIME + 大小校验(默认 image/jpeg,png,webp,gif;<=10MB),
 * 失败返回 HTTP 400 + { code: 400, message: '...' }。
 *
 * @param {string} filePath  uni.chooseImage 返回的本地临时路径
 * @returns {Promise<{objectKey:string, url:string}>}  上传成功的 OSS 对象 key + 完整 URL
 */
export function uploadChatImage(filePath) {
  const token = getToken()
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: '/api/chat/chat/upload/image',
      filePath,
      name: 'file',
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: (res) => {
        // uni.uploadFile.res.data 是字符串,需要手动 JSON.parse
        let body = null
        try { body = JSON.parse(res.data) } catch (e) { body = null }
        if (res.statusCode >= 200 && res.statusCode < 300 && body && body.code === 0) {
          resolve(body.data || {})
        } else {
          const msg = (body && (body.message || body.msg)) || `HTTP ${res.statusCode}`
          reject(new Error(msg))
        }
      },
      fail: (err) => reject(err)
    })
  })
}

function toArray(v) {
  if (Array.isArray(v)) return v
  if (v == null) return []
  return [v]
}

function pickText(obj, raw) {
  if (obj == null) return String(raw ?? '')
  if (typeof obj === 'string') return obj
  return obj.content ?? obj.text ?? obj.delta ?? obj.token ?? obj.answer ?? ''
}

/** 把一帧 SSE 事件按容错规则分派到对应回调，兼容多种事件命名 */
function dispatchChatEvent({ event, data }, cb) {
  let obj = null
  try { obj = JSON.parse(data) } catch (e) { obj = null }

  // 兼容包裹式：event 为通用 message，但 JSON 内自带 type/event 字段
  let type = (event || 'message').toLowerCase()
  if (type === 'message' && obj && (obj.type || obj.event)) {
    type = String(obj.type || obj.event).toLowerCase()
  }

  switch (type) {
    case 'token':
    case 'answer':
    case 'message':
    case 'delta':
      cb.onText && cb.onText(pickText(obj, data))
      break
    case 'product_card':
    case 'product_cards':
    case 'products':
      cb.onProductCards && cb.onProductCards(toArray(obj && (obj.productCards || obj.products || obj.data) || obj))
      break
    case 'confirm_card':
    case 'confirm':
      cb.onConfirm && cb.onConfirm((obj && (obj.confirmCard || obj.data)) || obj)
      break
    case 'cart_selection':
    case 'cart_list':
    case 'cart_selection_card':
      cb.onCartSelection && cb.onCartSelection((obj && (obj.cartSelection || obj.data)) || obj)
      break
    case 'routed':
    case 'route':
    case 'task_type':
      cb.onRouted && cb.onRouted((obj && (obj.taskType || obj.task_type)) || obj)
      break
    case 'orchestrator_plan':
      cb.onOrchestratorPlan && cb.onOrchestratorPlan(obj || {})
      break
    case 'orchestrator_subtask':
      cb.onOrchestratorSubtask && cb.onOrchestratorSubtask(obj || {})
      break
    case 'final': {
      // final 携带完整响应：在此提取卡片/路由。
      // 文本已由 token 增量给出，这里不再重复追加，避免答案显示两遍；
      // 仅在没有任何 token 文本时，由页面用 onFinalText 兜底补全（见 chat.vue）。
      if (obj) {
        const cards = obj.product_cards || obj.productCards
        if (cards && cards.length) cb.onProductCards && cb.onProductCards(toArray(cards))
        const confirm = obj.confirm_card || obj.confirmCard
        if (confirm) cb.onConfirm && cb.onConfirm(confirm)
        const cart = obj.cart_selection || obj.cartSelection
        if (cart) cb.onCartSelection && cb.onCartSelection(cart)
        const t = obj.task_type || obj.taskType
        if (t) cb.onRouted && cb.onRouted(t)
        // final 是编排链路的权威聚合结果；同时把完整 payload 传给页面，
        // 页面可以据 task_type 判断是否需要用聚合答案覆盖已流出的子任务标题/token。
        cb.onFinalText && cb.onFinalText(obj.answer || obj.content || '', obj)
      }
      break
    }
    case 'end':
    case 'done':
    case 'complete':
      cb.onDone && cb.onDone(obj || {})
      break
    case 'error':
      cb.onError && cb.onError(obj || { message: data })
      break
    default:
      // 未知事件名但带文本，当作增量兜底
      if (obj && pickText(obj, '')) cb.onText && cb.onText(pickText(obj, data))
      break
  }
}
