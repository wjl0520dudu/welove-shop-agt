<template>
  <view class="page history-page">
    <view class="toolbar">
      <view>
        <text class="title">浏览历史</text>
        <text class="subtitle">{{ subtitle }}</text>
      </view>
      <view class="refresh" @tap="loadHistory">
        <uni-icons type="refreshempty" size="16" color="#14b8a6" />
        <text>刷新</text>
      </view>
    </view>

    <view v-if="loading && !groups.length" class="state-wrap">
      <uni-load-more status="loading" :contentText="loadText" />
    </view>

    <view v-else-if="errorMessage && !groups.length" class="state-wrap">
      <EmptyState title="浏览历史加载失败" :description="errorMessage" />
      <button class="retry" @tap="loadHistory">重新加载</button>
    </view>

    <view v-else-if="groups.length" class="group-list">
      <view v-for="group in groups" :key="group.label" class="group">
        <view class="group-header">{{ group.label }}</view>
        <view v-for="item in group.items" :key="item.id || item.productId" class="history-card" @tap="goDetail(item.productId)">
          <image v-if="item.imageUrl && !imageErrorMap[item.id]" class="cover" :src="item.imageUrl" mode="aspectFill" @error="markImageFailed(item.id)" />
          <view v-else class="cover placeholder">
            <uni-icons type="image" size="28" color="#98a2b3" />
          </view>
          <view class="info">
            <text class="name">{{ item.productName }}</text>
            <text class="price">{{ item.priceText }}</text>
            <view class="meta-row">
              <text>{{ item.timeText }}</text>
              <text v-if="item.sourceText">{{ item.sourceText }}</text>
            </view>
          </view>
          <view class="remove" @tap.stop="confirmDelete(item)">
            <uni-icons type="trash" size="18" color="#98a2b3" />
          </view>
        </view>
      </view>
    </view>

    <EmptyState v-else title="暂无浏览历史" description="你查看过的商品会展示在这里。" />
  </view>
</template>

<script>
import EmptyState from '../../components/EmptyState.vue'
import { deleteBrowseHistory, getBrowseHistory } from '../../api/recommend'
import { requireLogin } from '../../utils/routeGuard'
import { buildImageUrl } from '../../utils/image'
import { formatMoney } from '../../utils/format'

export default {
  components: { EmptyState },
  data() {
    return {
      histories: [],
      loading: false,
      errorMessage: '',
      imageErrorMap: {},
      loadText: {
        contentdown: '加载更多',
        contentrefresh: '正在加载...',
        contentnomore: '没有更多了'
      }
    }
  },
  computed: {
    groups() {
      const map = new Map()
      this.histories.forEach((item) => {
        const label = this.groupLabel(item.date)
        if (!map.has(label)) map.set(label, [])
        map.get(label).push(item)
      })
      return Array.from(map.entries()).map(([label, items]) => ({ label, items }))
    },
    subtitle() {
      return this.histories.length ? `共 ${this.histories.length} 条记录` : '登录后可查看你的商品浏览记录'
    }
  },
  onLoad() {
    if (requireLogin('/pages/browse-history/browse-history')) this.loadHistory()
  },
  onShow() {
    if (requireLogin('/pages/browse-history/browse-history')) this.loadHistory()
  },
  onPullDownRefresh() {
    this.loadHistory().finally(() => uni.stopPullDownRefresh())
  },
  methods: {
    async loadHistory() {
      if (this.loading) return
      this.loading = true
      this.errorMessage = ''
      try {
        const data = await getBrowseHistory()
        const list = Array.isArray(data) ? data : (data?.records || [])
        this.histories = list.map(this.normalizeHistory).filter(item => item.id && item.productId)
      } catch (error) {
        this.errorMessage = error?.message || '请确认后端浏览历史接口已启动。'
      } finally {
        this.loading = false
      }
    },
    normalizeHistory(item = {}) {
      const product = item.product || {}
      const date = this.parseDate(item.createTime)
      const productId = Number(item.productId || product.id || 0)
      return {
        id: Number(item.id || 0),
        productId,
        productName: item.productName || product.title || product.name || '商品',
        imageUrl: buildImageUrl(item.productImage || product.imageUrl || product.productImage),
        priceText: formatMoney(item.productPrice ?? product.basePrice ?? product.price ?? 0),
        sourceText: this.sourceText(item.source),
        date,
        timeText: this.formatTime(date)
      }
    },
    parseDate(value) {
      if (!value) return null
      const normalized = String(value).replace('T', ' ').replace(/\.\d+$/, '')
      const date = new Date(normalized.replace(/-/g, '/'))
      return Number.isNaN(date.getTime()) ? null : date
    },
    formatTime(date) {
      if (!date) return '-'
      const hh = String(date.getHours()).padStart(2, '0')
      const mm = String(date.getMinutes()).padStart(2, '0')
      return `${hh}:${mm}`
    },
    groupLabel(date) {
      if (!date) return '更早'
      const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
      const today = startOfDay(new Date())
      const current = startOfDay(date)
      const diffDays = Math.floor((today - current) / 86400000)
      if (diffDays === 0) return '今天'
      if (diffDays === 1) return '昨天'
      if (diffDays >= 0 && diffDays < 7) return '本周'
      if (date.getFullYear() === today.getFullYear() && date.getMonth() === today.getMonth()) return '本月'
      return '更早'
    },
    sourceText(source) {
      const map = {
        detail: '详情页',
        search: '搜索',
        recommend: '推荐',
        chat: 'AI 导购'
      }
      return map[source] || ''
    },
    markImageFailed(id) {
      this.imageErrorMap = { ...this.imageErrorMap, [id]: true }
    },
    confirmDelete(item) {
      uni.showModal({
        title: '删除记录',
        content: `确定删除「${item.productName}」的浏览记录吗？`,
        confirmColor: '#f97316',
        success: (res) => {
          if (res.confirm) this.deleteItem(item)
        }
      })
    },
    async deleteItem(item) {
      const previous = this.histories
      this.histories = this.histories.filter(history => history.id !== item.id)
      try {
        await deleteBrowseHistory(item.id)
        uni.showToast({ title: '已删除', icon: 'success' })
      } catch (error) {
        this.histories = previous
        uni.showToast({ title: '删除失败', icon: 'none' })
      }
    },
    goDetail(productId) {
      if (!productId) return
      uni.navigateTo({ url: `/pages/product-detail/product-detail?id=${productId}` })
    }
  }
}
</script>

<style scoped>
.history-page {
  min-height: 100vh;
  padding: 24rpx 24rpx 120rpx;
  background: #f6fbfa;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20rpx;
}
.title {
  display: block;
  color: #1f2937;
  font-size: 34rpx;
  font-weight: 900;
}
.subtitle {
  display: block;
  margin-top: 6rpx;
  color: #667085;
  font-size: 24rpx;
}
.refresh {
  display: flex;
  align-items: center;
  gap: 6rpx;
  color: #14b8a6;
  font-size: 26rpx;
}
.group-list,
.group {
  display: flex;
  flex-direction: column;
  gap: 14rpx;
}
.group {
  gap: 12rpx;
}
.group + .group {
  margin-top: 12rpx;
}
.group-header {
  padding: 12rpx 4rpx 4rpx;
  color: #667085;
  font-size: 24rpx;
  font-weight: 800;
}
.history-card {
  display: flex;
  align-items: center;
  gap: 18rpx;
  padding: 18rpx;
  border-radius: 18rpx;
  background: #ffffff;
  box-shadow: 0 10rpx 28rpx rgba(15, 118, 110, 0.07);
}
.cover {
  flex: 0 0 auto;
  width: 144rpx;
  height: 144rpx;
  border-radius: 14rpx;
  background: #eef6f5;
}
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
}
.info {
  flex: 1;
  min-width: 0;
}
.name {
  display: block;
  overflow: hidden;
  color: #1f2937;
  font-size: 28rpx;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.price {
  display: block;
  margin-top: 10rpx;
  color: #f97316;
  font-size: 32rpx;
  font-weight: 900;
}
.meta-row {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-top: 8rpx;
  color: #98a2b3;
  font-size: 22rpx;
}
.remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 58rpx;
  height: 58rpx;
  border-radius: 50%;
  background: #f2f4f7;
}
.state-wrap {
  padding: 80rpx 0;
}
.retry {
  width: 240rpx;
  height: 72rpx;
  margin: 18rpx auto 0;
  border-radius: 999rpx;
  background: #14b8a6;
  color: #ffffff;
  font-size: 27rpx;
}
</style>
