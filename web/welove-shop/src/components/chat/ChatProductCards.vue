<template>
  <scroll-view scroll-x class="cards" :show-scrollbar="false">
    <view class="track">
      <view
        v-for="(item, index) in normalized"
        :key="item.id || index"
        class="card"
        @tap="$emit('open', item.raw)"
      >
        <image
          v-if="item.image && !failed[index]"
          class="thumb"
          :src="item.image"
          mode="aspectFill"
          @error="onError(index)"
        />
        <view v-else class="thumb placeholder">
          <uni-icons type="image" size="26" color="#98a2b3" />
        </view>
        <view class="body">
          <view class="title-row">
            <text class="title">{{ item.title }}</text>
            <text v-if="item.isAlternative" class="reference-badge">店内参考</text>
          </view>
          <text v-if="item.reason" class="reason">{{ item.reason }}</text>
          <text v-if="item.gapMessage" class="gap">{{ item.gapMessage }}</text>
          <view class="bottom">
            <text class="price">{{ item.price }}</text>
            <view class="add" @tap.stop="$emit('add', item.raw)">
              <uni-icons type="cart" size="15" color="#ffffff" />
              <text>加购</text>
            </view>
          </view>
        </view>
      </view>
    </view>
  </scroll-view>
</template>

<script>
import { formatMoney } from '../../utils/format'
import { buildImageUrl, pickProductImage } from '../../utils/image'
import { getProductDetail } from '../../api/product'

export default {
  name: 'ChatProductCards',
  props: {
    products: { type: Array, default: () => [] }
  },
  emits: ['open', 'add'],
  data() {
    return {
      failed: {},
      detailImages: {},
      loadingImageIds: {}
    }
  },
  computed: {
    normalized() {
      return (this.products || []).map((p) => {
        // ai-service 卡片字段是 product_id（下划线），兼容 productId/id 多种来源
        const pid = p.productId || p.id || p.product_id
        return {
          id: pid,
          title: p.title || p.name || p.productTitle || '好物推荐',
          reason: p.reason || p.recommendReason || p.desc || '',
          isAlternative: (p.matchStatus || p.match_status) === 'alternative',
          gapMessage: this.firstGapMessage(p),
          price: formatMoney(p.price ?? p.basePrice ?? p.base_price ?? p.skuPrice ?? 0),
          image: this.cardImage(p, pid),
          raw: { ...p, id: pid, productId: pid }
        }
      })
    }
  },
  watch: {
    products: {
      immediate: true,
      handler() {
        this.failed = {}
        this.loadProductImages()
      }
    }
  },
  methods: {
    cardImage(product, productId) {
      if (productId) {
        const key = String(productId)
        return this.detailImages[key] ? buildImageUrl(this.detailImages[key]) : ''
      }
      return buildImageUrl(pickProductImage(product))
    },
    firstGapMessage(product) {
      const gaps = product.constraintGaps || product.constraint_gaps || []
      if (!Array.isArray(gaps) || !gaps.length) return ''
      const gap = gaps[0] || {}
      return gap.message || gap.reason || [gap.name, gap.expected, gap.actual].filter(Boolean).join(': ')
    },
    loadProductImages() {
      const ids = Array.from(new Set(
        (this.products || [])
          .map(item => item.productId || item.id || item.product_id)
          .filter(Boolean)
          .map(String)
      ))
      ids.forEach((id) => {
        if (Object.prototype.hasOwnProperty.call(this.detailImages, id) || this.loadingImageIds[id]) return
        this.loadingImageIds = { ...this.loadingImageIds, [id]: true }
        getProductDetail(id)
          .then((detail = {}) => {
            const product = detail.product || detail
            const images = Array.isArray(detail.images) ? detail.images : []
            const image = pickProductImage(product) ||
              pickProductImage(detail) ||
              (images[0] && (images[0].imageUrl || images[0].image_url || images[0].url)) ||
              ''
            this.detailImages = { ...this.detailImages, [id]: image }
            this.failed = {}
          })
          .catch(() => {
            const original = (this.products || []).find(item => String(item.productId || item.id || item.product_id) === id)
            this.detailImages = { ...this.detailImages, [id]: pickProductImage(original || {}) }
          })
          .finally(() => {
            const next = { ...this.loadingImageIds }
            delete next[id]
            this.loadingImageIds = next
          })
      })
    },
    onError(index) {
      this.failed = { ...this.failed, [index]: true }
    }
  }
}
</script>

<style scoped>
.cards {
  width: 100%;
  white-space: nowrap;
}
.track {
  display: inline-flex;
  gap: 16rpx;
  padding: 6rpx 2rpx 4rpx;
}
.card {
  display: inline-flex;
  flex-direction: column;
  width: 240rpx;
  overflow: hidden;
  border-radius: 20rpx;
  background: #ffffff;
  box-shadow: 0 12rpx 28rpx rgba(15, 118, 110, 0.1);
}
.thumb {
  width: 240rpx;
  height: 200rpx;
  background: #eef6f5;
}
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
}
.body {
  padding: 16rpx;
}
.title {
  flex: 1;
  display: -webkit-box;
  overflow: hidden;
  height: 74rpx;
  color: #1f2937;
  font-size: 26rpx;
  font-weight: 700;
  line-height: 1.4;
  white-space: normal;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.title-row {
  display: flex;
  align-items: flex-start;
  gap: 8rpx;
}
.reference-badge {
  flex-shrink: 0;
  margin-top: 2rpx;
  padding: 3rpx 8rpx;
  border-radius: 8rpx;
  background: #fff3e0;
  color: #b54708;
  font-size: 18rpx;
  font-weight: 700;
}
.gap {
  display: block;
  margin-top: 6rpx;
  overflow: hidden;
  color: #b54708;
  font-size: 20rpx;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.reason {
  display: block;
  margin-top: 6rpx;
  overflow: hidden;
  color: #98a2b3;
  font-size: 21rpx;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12rpx;
}
.price {
  color: #f97316;
  font-size: 28rpx;
  font-weight: 800;
}
.add {
  display: flex;
  align-items: center;
  gap: 6rpx;
  flex-shrink: 0;
  padding: 10rpx 18rpx;
  border-radius: 999rpx;
  background: #14b8a6;
  color: #ffffff;
  font-size: 22rpx;
  font-weight: 700;
  white-space: nowrap;
}
</style>
