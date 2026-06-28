export function formatMoney(value) {
  const number = Number(value || 0)
  return `¥${number.toFixed(2)}`
}

export function orderStatusText(status) {
  const map = {
    0: '待付款',
    1: '待发货',
    2: '待收货',
    3: '已完成',
    4: '已取消'
  }
  return map[status] || '未知状态'
}
