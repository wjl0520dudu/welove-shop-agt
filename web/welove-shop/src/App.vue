<script>
import userStore from './store/user'
import cartStore from './store/cart'

export default {
  onLaunch() {
    userStore.restore()
    if (userStore.isLoggedIn()) {
      cartStore.beginSession()
      cartStore.refreshAndSyncBadge().catch(() => {})
    } else {
      cartStore.reset()
    }
  },
  onShow() {
    // 首次写入发生在 TabBar 未就绪时，恢复到前台时再同步一次。
    cartStore.flushBadge()
  },
  onHide() {}
}
</script>

<style lang="scss">
@import '@/uni_modules/uni-scss/index.scss';

/* ===== 设计令牌（青绿主 + 橙辅），供新样式引用 ===== */
page {
  --brand: #14b8a6;
  --brand-deep: #0f766e;
  --brand-pale: #f0fdfa;
  --accent: #f97316;
  --accent-pale: #fff7ed;
  --bg: #f4f8f8;
  --surface: #ffffff;
  --text: #1f2937;
  --text-muted: #667085;
  --text-hint: #98a2b3;
  --border: #e5e7eb;
  --shadow: 0 12rpx 34rpx rgba(15, 118, 110, 0.08);

  min-height: 100%;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.page {
  min-height: 100vh;
  box-sizing: border-box;
  background: var(--bg);
  /* 仅淡入不位移：避免 transform 令 position:fixed 元素错位 */
  animation: page-fade 0.28s ease both;
}
@keyframes page-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

.page-body {
  padding: 24rpx;
}

.section {
  margin-bottom: 24rpx;
  padding: 28rpx;
  border: 1rpx solid rgba(20, 184, 166, 0.08);
  border-radius: 22rpx;
  background: var(--surface);
  box-shadow: 0 10rpx 30rpx rgba(15, 118, 110, 0.06);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.title {
  display: block;
  font-size: 38rpx;
  font-weight: 800;
  color: var(--text);
}

.subtitle {
  display: block;
  margin-top: 8rpx;
  font-size: 26rpx;
  color: var(--text-muted);
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
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.input:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 4rpx rgba(20, 184, 166, 0.12);
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
  transition: transform 0.16s ease, box-shadow 0.16s ease, opacity 0.16s ease;
}
.primary-button:active,
button.primary-button:active {
  transform: scale(0.97);
  box-shadow: 0 6rpx 16rpx rgba(20, 184, 166, 0.2);
  opacity: 0.94;
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
  transition: transform 0.16s ease, opacity 0.16s ease;
}
.secondary-button:active,
button.secondary-button:active {
  transform: scale(0.97);
  opacity: 0.9;
}

.price {
  color: #f97316;
  font-weight: 800;
}

button::after {
  border: 0;
}

/* ===== 通用动效工具 ===== */
.fade-in-up {
  animation: fade-in-up 0.34s cubic-bezier(0.22, 1, 0.36, 1) both;
}
@keyframes fade-in-up {
  from { opacity: 0; transform: translateY(16rpx); }
  to { opacity: 1; transform: translateY(0); }
}

/* 骨架屏 / 图片占位微光 */
.skeleton {
  background: linear-gradient(100deg, #eef2f4 30%, #f6f9fa 50%, #eef2f4 70%);
  background-size: 200% 100%;
  animation: shimmer 1.3s ease-in-out infinite;
}
@keyframes shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

/* H5 更纤细的滚动条 */
/* #ifdef H5 */
::-webkit-scrollbar {
  width: 8rpx;
  height: 8rpx;
}
::-webkit-scrollbar-thumb {
  border-radius: 999rpx;
  background: rgba(15, 118, 110, 0.18);
}
::-webkit-scrollbar-track {
  background: transparent;
}
/* #endif */
</style>
