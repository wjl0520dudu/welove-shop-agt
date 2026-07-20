import request from '../utils/request'

/**
 * 支付宝支付 API
 *
 * 流程(对接 trade-service 的 AlipayController / AlipayNotifyController):
 *   1. createAlipayForm(orderId)  → 后端按 pay-mode 返回支付宝 H5/PC HTML 表单
 *   2. 前端提交 HTML 表单 → 浏览器跳到支付宝收银台
 *   3. 用户在支付宝付款 → 浏览器跳到 return-url(我们的支付结果页)
 *   4. 后端异步通知(notify-url) → 改订单状态
 *   5. 用户在结果页轮询 getPayStatus(orderId) → 直到状态变为已支付/已关闭
 */

/**
 * 创建支付宝支付表单
 * @param {number} orderId 订单 ID
 * @returns {Promise<string>} HTML 字符串(含 form + 自动提交 JS)
 */
export function createAlipayForm(orderId) {
  return request({
    url: `/api/trade/alipay/create/${orderId}`,
    method: 'POST',
    header: { 'Content-Type': 'application/json' },
    data: {},
    // 关键: 后端返回 text/html,不走 JSON.parse,request 工具需要原始字符串
    // 但 request 工具默认会按 JSON 解,所以这里我们用 plain text 的兜底
    responseType: 'text'
  }).then((raw) => {
    // request 工具在 body.code 不存在时,会原样返回 response.data
    // 如果 responseType: text 生效,data 就是字符串
    if (typeof raw === 'string') {
      const text = raw.trim()
      // responseType=text 时,后端异常也会以 JSON 字符串返回。不要把错误 JSON
      // 当成支付 HTML,否则页面只会提示"支付表单解析失败"而丢失真实原因。
      if (text.startsWith('{')) {
        try {
          const payload = JSON.parse(text)
          if (payload && Object.prototype.hasOwnProperty.call(payload, 'code')) {
            if (payload.code !== 0 && payload.code !== 200) {
              throw new Error(payload.message || '创建支付单失败')
            }
            return payload.data || ''
          }
        } catch (error) {
          // 以 { 开头但不是 JSON 的 HTML 仍按原文继续交给表单解析。
          if (!(error instanceof SyntaxError)) throw error
        }
      }
      return text
    }
    // 兼容后端被网关或代理拦截返回 JSON 的兜底
    if (raw && typeof raw === 'object') return raw.html || raw.data || JSON.stringify(raw)
    return String(raw)
  })
}

/**
 * 在 H5 中提交支付宝返回的 form。
 *
 * 支付宝 H5/电脑网站支付都是 POST 表单,不能用 uni.navigateTo 或 window.open
 * 代替;同时直接 innerHTML 注入的 script 不会可靠执行,所以复制表单字段后
 * 使用浏览器原生 HTMLFormElement.submit() 发起同页跳转。
 */
export function submitAlipayForm(html) {
  if (typeof document === 'undefined' || typeof DOMParser === 'undefined') {
    throw new Error('支付宝网页支付仅支持 H5 浏览器')
  }

  const doc = new DOMParser().parseFromString(String(html || ''), 'text/html')
  const sourceForm = doc.querySelector('form')
  const action = sourceForm && (sourceForm.getAttribute('action') || sourceForm.action)
  if (!sourceForm || !action) {
    throw new Error('支付表单解析失败')
  }

  const liveForm = document.createElement('form')
  liveForm.method = (sourceForm.getAttribute('method') || 'POST').toUpperCase()
  liveForm.action = action
  liveForm.target = '_self'
  liveForm.style.display = 'none'

  // EasySDK 生成的支付宝表单字段都是 hidden input。保留 name/value,
  // 跳过按钮等非参数控件,避免把展示控件一并提交给支付宝。
  sourceForm.querySelectorAll('input[name]').forEach((input) => {
    const type = (input.getAttribute('type') || 'text').toLowerCase()
    if (['submit', 'button', 'reset', 'file'].includes(type) || input.disabled) return
    const liveInput = document.createElement('input')
    liveInput.type = 'hidden'
    liveInput.name = input.name
    liveInput.value = input.value
    liveForm.appendChild(liveInput)
  })

  document.body.appendChild(liveForm)
  // 避免表单中存在 name=submit 时遮蔽实例方法。
  HTMLFormElement.prototype.submit.call(liveForm)
}

/**
 * 查询支付状态(轮询用)
 * @param {number} orderId 订单 ID
 * @returns {Promise<{
 *   orderNo: string,
 *   orderStatus: number,   // 0=待支付,1=已支付,2=已发货,3=已完成,4=已关闭
 *   tradeNo: string|null,  // 支付宝交易号(支付成功后才有)
 *   tradeStatus: string|null,
 *   payAmount: string,
 *   payChannel: string     // ALIPAY / MOCK
 * }>}
 */
export function getPayStatus(orderId) {
  return request({
    url: `/api/trade/alipay/status/${orderId}`,
    method: 'GET'
  })
}

/**
 * 关闭支付(取消未支付订单时调用)
 * @param {number} orderId 订单 ID
 */
export function closePay(orderId) {
  return request({
    url: `/api/trade/alipay/close/${orderId}`,
    method: 'POST',
    header: { 'Content-Type': 'application/json' },
    data: {}
  })
}
