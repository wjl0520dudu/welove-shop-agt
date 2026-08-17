import { reactive } from 'vue'
import { getCartCount, getCartList } from '../api/cart'

const TAB_BAR_CART_INDEX = 2

// 响应式 state：页面内绑定 cartStore.state.count 的地方能随加购实时刷新
const state = reactive({
  count: 0,
  items: []
})

// 切换登录用户或退出时递增，旧请求返回后不能把旧用户购物车写回。
let sessionVersion = 0
// 购物车内容发生改变后，之前已经发出的列表/数量请求不能再覆盖新状态。
let cartRevision = 0

function normalizeCount(value) {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : 0
}

export default {
  state,
  async refreshCount() {
    const version = sessionVersion
    const revision = cartRevision
    const count = normalizeCount(await getCartCount())
    if (version !== sessionVersion || revision !== cartRevision) return state.count
    state.count = count
    this.syncBadge(state.count)
    return state.count
  },
  async refreshAndSyncBadge() {
    await this.loadCart()
    return state.count
  },
  async loadCart() {
    const version = sessionVersion
    const revision = cartRevision
    const data = await getCartList()
    const items = Array.isArray(data) ? data : (data?.records || data?.items || data?.list || [])
    if (version !== sessionVersion || revision !== cartRevision) return state.items
    state.items = items
    state.count = items.reduce((sum, item) => sum + Number(item.quantity || 0), 0)
    this.syncBadge(state.count)
    return state.items
  },
  /** 乐观更新：取数接口失败时也能让角标先动起来，返回更新后的值 */
  bump(delta = 1) {
    cartRevision += 1
    state.count = Math.max(0, Number(state.count || 0) + delta)
    this.syncBadge(state.count)
    return state.count
  },
  syncBadge(count = state.count) {
    const c = normalizeCount(count)
    state.count = c
    if (typeof uni === 'undefined') return c
    const apply = () => new Promise((resolve, reject) => {
      const options = {
        index: TAB_BAR_CART_INDEX,
        success: resolve,
        fail: reject
      }
      if (c > 0) {
        uni.setTabBarBadge({ ...options, text: String(c > 99 ? '99+' : c) })
      } else {
        uni.removeTabBarBadge(options)
      }
    })
    const retry = (attempt = 0) => {
      try {
        Promise.resolve(apply())
          .catch(() => {
            if (attempt < 2 && c === state.count) setTimeout(() => retry(attempt + 1), 120)
          })
      } catch (error) {
        if (attempt < 2 && c === state.count) setTimeout(() => retry(attempt + 1), 120)
      }
    }
    retry()
    return c
  },
  flushBadge() {
    // 即使没有待刷标记也同步一次，避免 H5 TabBar 重建后遗失徽标。
    return this.syncBadge(state.count)
  },
  beginSession() {
    sessionVersion += 1
    cartRevision += 1
    state.count = 0
    state.items = []
    this.syncBadge(0)
    return sessionVersion
  },
  reset() {
    return this.beginSession()
  }
}
