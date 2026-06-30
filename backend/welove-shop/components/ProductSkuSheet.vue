<template>
  <view v-if="visible" class="mask" @tap="$emit('close')">
    <view class="sheet" @tap.stop>
      <view class="handle"></view>
      <view class="head">
        <view>
          <text class="title">选择规格</text>
          <text class="summary">{{ selectedSummary }}</text>
        </view>
        <view class="close" @tap="$emit('close')">
          <uni-icons type="closeempty" size="22" color="#667085" />
        </view>
      </view>

      <scroll-view scroll-y class="sku-list">
        <view
          v-for="(sku, index) in skus"
          :key="sku.id || index"
          class="sku-item"
          :class="{ active: selectedIndex === index, disabled: getStock(sku) <= 0 }"
          @tap="select(index)"
        >
          <view class="sku-main">
            <text class="sku-name">{{ formatProperties(sku) }}</text>
            <text class="sku-stock">库存 {{ getStock(sku) }}</text>
          </view>
          <text class="sku-price">¥{{ formatPrice(sku.price) }}</text>
        </view>
      </scroll-view>

      <button class="confirm" :disabled="!selectedSku || getStock(selectedSku) <= 0" @tap="confirm">确定</button>
    </view>
  </view>
</template>

<script>
import { formatMoney } from '../utils/format'

export default {
  name: 'ProductSkuSheet',
  props: {
    visible: { type: Boolean, default: false },
    skus: { type: Array, default: () => [] },
    defaultIndex: { type: Number, default: 0 }
  },
  emits: ['close', 'confirm'],
  data() {
    return { selectedIndex: 0 }
  },
  computed: {
    selectedSku() {
      return this.skus[this.selectedIndex] || null
    },
    selectedSummary() {
      return this.selectedSku ? this.formatProperties(this.selectedSku) : '暂无可选规格'
    }
  },
  watch: {
    visible(value) {
      if (value) this.resetSelected()
    },
    skus() {
      this.resetSelected()
    }
  },
  mounted() {
    this.resetSelected()
  },
  methods: {
    resetSelected() {
      const defaultIndex = this.skus.findIndex(item => item.isDefault === true || item.isDefault === 1)
      const next = defaultIndex >= 0 ? defaultIndex : this.defaultIndex
      this.selectedIndex = Math.min(Math.max(next, 0), Math.max(this.skus.length - 1, 0))
    },
    select(index) {
      const sku = this.skus[index]
      if (!sku || this.getStock(sku) <= 0) return
      this.selectedIndex = index
    },
    confirm() {
      if (!this.selectedSku || this.getStock(this.selectedSku) <= 0) return
      this.$emit('confirm', this.selectedSku)
    },
    formatProperties(sku) {
      const properties = sku.properties || {}
      if (typeof properties === 'string') return properties || '默认规格'
      const text = Object.keys(properties).map(key => `${key}: ${properties[key]}`).join('  ')
      return text || sku.skuCode || '默认规格'
    },
    formatPrice(price) {
      return formatMoney(price)
    },
    getStock(sku) {
      return Number(sku.stock || 0)
    }
  }
}
</script>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  z-index: 99;
  display: flex;
  align-items: flex-end;
  background: rgba(15, 23, 42, 0.42);
}
.sheet {
  width: 100%;
  max-height: 78vh;
  padding: 18rpx 24rpx 34rpx;
  border-radius: 28rpx 28rpx 0 0;
  background: #ffffff;
}
.handle {
  width: 72rpx;
  height: 8rpx;
  margin: 0 auto 22rpx;
  border-radius: 999rpx;
  background: #d0d5dd;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 22rpx;
}
.title {
  display: block;
  color: #101828;
  font-size: 34rpx;
  font-weight: 800;
}
.summary {
  display: block;
  margin-top: 8rpx;
  color: #667085;
  font-size: 24rpx;
}
.close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 58rpx;
  height: 58rpx;
  border-radius: 50%;
  background: #f2f4f7;
}
.sku-list {
  max-height: 52vh;
}
.sku-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18rpx;
  margin-bottom: 16rpx;
  padding: 22rpx;
  border: 2rpx solid #e4e7ec;
  border-radius: 18rpx;
  background: #ffffff;
}
.sku-item.active {
  border-color: #14b8a6;
  background: #ecfdf9;
}
.sku-item.disabled {
  opacity: 0.46;
}
.sku-main {
  flex: 1;
  min-width: 0;
}
.sku-name {
  display: block;
  color: #1f2937;
  font-size: 27rpx;
  font-weight: 700;
  line-height: 1.35;
}
.sku-stock {
  display: block;
  margin-top: 8rpx;
  color: #667085;
  font-size: 23rpx;
}
.sku-price {
  color: #f97316;
  font-size: 30rpx;
  font-weight: 800;
}
.confirm {
  height: 88rpx;
  margin-top: 18rpx;
  border-radius: 999rpx;
  background: #14b8a6;
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 800;
}
.confirm[disabled] {
  background: #d0d5dd;
  color: #ffffff;
}
</style>
