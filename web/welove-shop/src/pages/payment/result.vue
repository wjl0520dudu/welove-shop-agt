<template>
  <view class="page result-page">
    <view v-if="state === 'loading'" class="state-block">
      <view class="spinner" />
      <text class="state-title">支付处理中</text>
      <text class="state-desc">正在确认支付结果,请稍候...</text>
    </view>

    <view v-else-if="state === 'success'" class="state-block">
      <view class="icon success">✓</view>
      <text class="state-title">支付成功</text>
      <text class="state-desc">订单已支付,商家将尽快为您发货</text>
      <view class="order-info">
        <view class="info-row"><text class="label">订单号</text><text>{{ orderNo }}</text></view>
        <view class="info-row"><text class="label">支付金额</text><text class="amount">¥{{ payAmount }}</text></view>
        <view class="info-row" v-if="tradeNo"><text class="label">支付宝交易号</text><text>{{ tradeNo }}</text></view>
      </view>
      <view class="action-row">
        <button class="primary-btn" @tap="goOrderDetail">查看订单</button>
        <button class="outline-btn" @tap="goOrderList">返回订单列表</button>
      </view>
    </view>

    <view v-else-if="state === 'failed'" class="state-block">
      <view class="icon failed">✕</view>
      <text class="state-title">支付未完成</text>
      <text class="state-desc">{{ failReason || '订单尚未支付成功,您可以重新尝试' }}</text>
      <view class="action-row">
        <button class="primary-btn" @tap="retryPay">重新支付</button>
        <button class="outline-btn" @tap="goOrderDetail">查看订单</button>
      </view>
    </view>

    <view v-else-if="state === 'closed'" class="state-block">
      <view class="icon failed">✕</view>
      <text class="state-title">订单已关闭</text>
      <text class="state-desc">该订单已超时关闭,请重新下单</text>
      <view class="action-row">
        <button class="primary-btn" @tap="goHome">返回首页</button>
      </view>
    </view>
  </view>
</template>

<script>
import { getPayStatus } from '../../api/payment'

export default {
  data() {
    return {
      orderId: null,
      orderNo: '',
      payAmount: '',
      tradeNo: '',
      state: 'loading',       // loading | success | failed | closed
      failReason: '',
      pollTimer: null,
      maxPollCount: 30        // 最多轮询 30 次(2s 一次,共 60s)
    }
  },
  onLoad(query = {}) {
    this.orderId = Number(query.orderId || query.out_trade_no || 0)
    if (!this.orderId) {
      uni.showToast({ title: '参数错误', icon: 'none' })
      setTimeout(() => uni.navigateBack(), 800)
      return
    }
    this.startPoll()
  },
  onUnload() {
    this.stopPoll()
  },
  onHide() {
    this.stopPoll()
  },
  methods: {
    startPoll() {
      // 立即查一次,再启动轮询
      this.pollOnce()
      let count = 0
      this.pollTimer = setInterval(() => {
        count++
        if (count > this.maxPollCount) {
          this.stopPoll()
          // 超时后兜底:展示订单当前状态,不强制失败
          this.fetchStatus()
          return
        }
        this.pollOnce()
      }, 2000)
    },
    stopPoll() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },
    async pollOnce() {
      try {
        const data = await getPayStatus(this.orderId)
        this.applyStatus(data)
        // 一旦终态,停止轮询
        if (['success', 'failed', 'closed'].includes(this.state)) {
          this.stopPoll()
        }
      } catch (e) {
        // 静默失败,继续轮询
      }
    },
    async fetchStatus() {
      try {
        const data = await getPayStatus(this.orderId)
        this.applyStatus(data)
      } catch (e) {
        this.state = 'failed'
        this.failReason = '查询订单状态失败,请返回订单列表查看'
      }
    },
    applyStatus(data) {
      if (!data) return
      this.orderNo = data.orderNo || ''
      this.payAmount = data.payAmount || ''
      this.tradeNo = data.tradeNo || ''

      // orderStatus: 0=待支付,1=已支付,2=已发货,3=已完成,4=已关闭
      const status = Number(data.orderStatus)
      if (status === 1 || status === 2 || status === 3) {
        this.state = 'success'
      } else if (status === 4) {
        this.state = 'closed'
      } else {
        this.state = 'loading'
      }
    },
    goOrderDetail() {
      uni.redirectTo({ url: `/pages/order-detail/order-detail?id=${this.orderId}` })
    },
    goOrderList() {
      uni.redirectTo({ url: '/pages/order-list/order-list' })
    },
    goHome() {
      uni.switchTab({ url: '/pages/product-list/product-list' })
    },
    retryPay() {
      // 跳回订单详情,让用户重新点"立即支付"
      uni.redirectTo({ url: `/pages/order-detail/order-detail?id=${this.orderId}` })
    }
  }
}
</script>

<style scoped>
.result-page {
  min-height: 100vh;
  background: #f6f7f9;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40rpx 32rpx;
}
.state-block {
  width: 100%;
  background: #fff;
  border-radius: 24rpx;
  padding: 80rpx 40rpx 60rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  box-shadow: 0 10rpx 28rpx rgba(15, 118, 110, 0.06);
}
.spinner {
  width: 80rpx;
  height: 80rpx;
  border: 6rpx solid #eef2f7;
  border-top-color: #14b8a6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.icon {
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 70rpx;
  font-weight: 900;
  color: #fff;
}
.icon.success { background: #14b8a6; }
.icon.failed { background: #ef4444; }
.state-title {
  display: block;
  margin-top: 30rpx;
  font-size: 40rpx;
  font-weight: 900;
  color: #1f2937;
}
.state-desc {
  display: block;
  margin-top: 12rpx;
  font-size: 26rpx;
  color: #667085;
  text-align: center;
  line-height: 1.5;
}
.order-info {
  width: 100%;
  margin-top: 40rpx;
  padding: 30rpx 24rpx;
  background: #f9fafb;
  border-radius: 16rpx;
}
.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10rpx 0;
  font-size: 26rpx;
  color: #344054;
}
.info-row .label { color: #98a2b3; }
.info-row .amount { color: #f97316; font-size: 30rpx; font-weight: 900; }
.action-row {
  width: 100%;
  margin-top: 50rpx;
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}
.primary-btn, .outline-btn {
  height: 84rpx;
  border-radius: 999rpx;
  font-size: 29rpx;
  font-weight: 900;
  line-height: 84rpx;
}
.primary-btn { background: #14b8a6; color: #fff; }
.outline-btn { background: #fff; color: #667085; border: 1rpx solid #d0d5dd; }
</style>