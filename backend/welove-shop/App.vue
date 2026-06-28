<script>
import userStore from './store/user'

export default {
  onLaunch() {
    userStore.restore()
    console.log('ShopAgent-X uni-app launch')
  },
  onShow() {
    console.log('ShopAgent-X uni-app show')
  },
  onHide() {
    console.log('ShopAgent-X uni-app hide')
  }
}
</script>

<style lang="scss">
@import '@/uni_modules/uni-scss/index.scss';

page {
  min-height: 100%;
  background: #f4f8f8;
  color: #1f2937;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.page {
  min-height: 100vh;
  box-sizing: border-box;
  background: #f4f8f8;
}

.page-body {
  padding: 24rpx;
}

.section {
  margin-bottom: 24rpx;
  padding: 28rpx;
  border: 1rpx solid rgba(20, 184, 166, 0.08);
  border-radius: 22rpx;
  background: #ffffff;
  box-shadow: 0 10rpx 30rpx rgba(15, 118, 110, 0.06);
}

.title {
  display: block;
  font-size: 38rpx;
  font-weight: 800;
  color: #1f2937;
}

.subtitle {
  display: block;
  margin-top: 8rpx;
  font-size: 26rpx;
  color: #667085;
  line-height: 1.5;
}

.input {
  height: 88rpx;
  box-sizing: border-box;
  padding: 0 24rpx;
  border: 1rpx solid #dbe5e3;
  border-radius: 16rpx;
  background: #ffffff;
  font-size: 28rpx;
}

.primary-button,
button.primary-button {
  height: 88rpx;
  border: 0;
  border-radius: 999rpx;
  background: linear-gradient(135deg, #14b8a6, #0f766e);
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 700;
  line-height: 88rpx;
  box-shadow: 0 12rpx 28rpx rgba(20, 184, 166, 0.24);
}

.secondary-button,
button.secondary-button {
  height: 82rpx;
  border: 1rpx solid #fed7aa;
  border-radius: 999rpx;
  background: #fff7ed;
  color: #f97316;
  font-size: 28rpx;
  font-weight: 700;
  line-height: 82rpx;
}

.price {
  color: #f97316;
  font-weight: 800;
}

button::after {
  border: 0;
}
</style>
