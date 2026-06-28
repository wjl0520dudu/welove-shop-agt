export function normalizeAmount(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

export function formatAmount(value, digits = 2) {
  return normalizeAmount(value).toFixed(digits)
}

export function formatMoney(value, options = {}) {
  const { symbol = '\u00a5', digits = 2 } = options
  return `${symbol}${formatAmount(value, digits)}`
}

export function orderStatusText(status) {
  const map = {
    0: '\u5f85\u4ed8\u6b3e',
    1: '\u5f85\u53d1\u8d27',
    2: '\u5f85\u6536\u8d27',
    3: '\u5df2\u5b8c\u6210',
    4: '\u5df2\u53d6\u6d88'
  }
  return map[status] || '\u672a\u77e5\u72b6\u6001'
}
