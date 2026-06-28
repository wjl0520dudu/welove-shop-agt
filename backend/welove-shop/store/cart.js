import { getCartCount, getCartList } from '../api/cart'

const state = {
  count: 0,
  items: []
}

export default {
  state,
  async refreshCount() {
    state.count = await getCartCount()
    return state.count
  },
  async loadCart() {
    const data = await getCartList()
    state.items = Array.isArray(data) ? data : (data?.records || data?.items || data?.list || [])
    state.count = state.items.reduce((sum, item) => sum + Number(item.quantity || 0), 0)
    return state.items
  },
  reset() {
    state.count = 0
    state.items = []
  }
}
