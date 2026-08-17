<template>
  <view class="page setup-page">
    <view class="setup-head">
      <view class="progress-track">
        <view class="progress-fill" :style="{ width: progressWidth }"></view>
      </view>
      <view class="head-row">
        <text class="step-index">{{ step + 1 }} / {{ steps.length }}</text>
        <text class="skip" @tap="skip">跳过</text>
      </view>
    </view>

    <view class="setup-body">
      <text class="q-title">{{ current.title }}</text>
      <text class="q-sub">{{ current.subtitle }}</text>

      <!-- 性别 -->
      <view v-if="current.key === 'gender'" class="options">
        <view
          v-for="g in genders"
          :key="g.value"
          class="option"
          :class="{ active: form.gender === g.value }"
          @tap="form.gender = g.value"
        >
          <text>{{ g.label }}</text>
          <uni-icons v-if="form.gender === g.value" type="checkmarkempty" size="18" color="#14b8a6" />
        </view>
      </view>

      <!-- 年龄段 -->
      <view v-else-if="current.key === 'ageRange'" class="options">
        <view
          v-for="age in ageRanges"
          :key="age"
          class="option"
          :class="{ active: form.ageRange === age }"
          @tap="form.ageRange = age"
        >
          <text>{{ age }} 岁</text>
          <uni-icons v-if="form.ageRange === age" type="checkmarkempty" size="18" color="#14b8a6" />
        </view>
      </view>

      <!-- 肤质 -->
      <view v-else-if="current.key === 'skinType'" class="chip-wrap">
        <view
          v-for="skin in skinTypes"
          :key="skin"
          class="chip"
          :class="{ active: form.skinType === skin }"
          @tap="form.skinType = skin"
        >{{ skin }}</view>
      </view>

      <!-- 偏好标签 -->
      <scroll-view v-else scroll-y class="tag-scroll">
        <view v-for="group in preferenceGroups" :key="group.title" class="tag-group">
          <text class="group-title">{{ group.title }}</text>
          <view class="chip-wrap">
            <view
              v-for="tag in group.tags"
              :key="tag"
              class="chip"
              :class="{ active: form.preferenceTags.includes(tag) }"
              @tap="toggleTag(tag)"
            >{{ tag }}</view>
          </view>
        </view>
      </scroll-view>
    </view>

    <view class="setup-footer">
      <view v-if="step > 0" class="btn ghost" @tap="prev">上一步</view>
      <view class="btn primary" :class="{ loading }" @tap="next">{{ isLast ? '完成' : '下一步' }}</view>
    </view>
  </view>
</template>

<script>
import { updateProfile } from '../../api/auth'
import userStore from '../../store/user'
import { requireLogin } from '../../utils/routeGuard'
import { GENDERS, AGE_RANGES, SKIN_TYPES, PREFERENCE_GROUPS, normalizeTags } from '../../utils/persona'

export default {
  data() {
    return {
      step: 0,
      loading: false,
      redirect: '',
      genders: GENDERS,
      ageRanges: AGE_RANGES,
      skinTypes: SKIN_TYPES,
      preferenceGroups: PREFERENCE_GROUPS,
      steps: [
        { key: 'gender', title: '你的性别是？', subtitle: '帮助我们推荐更合适的商品' },
        { key: 'ageRange', title: '你的年龄段？', subtitle: '不同年龄的偏好会有所不同' },
        { key: 'skinType', title: '你的肤质类型？', subtitle: '用于精准推荐护肤好物' },
        { key: 'preferenceTags', title: '你更关注什么？', subtitle: '可多选，随时可在资料中修改' }
      ],
      form: {
        gender: null,
        ageRange: '',
        skinType: '',
        preferenceTags: []
      }
    }
  },
  computed: {
    current() { return this.steps[this.step] },
    isLast() { return this.step === this.steps.length - 1 },
    progressWidth() { return `${((this.step + 1) / this.steps.length) * 100}%` }
  },
  onLoad(query) {
    if (!requireLogin('/pages/profile-setup/profile-setup')) return
    this.redirect = decodeURIComponent((query && query.redirect) || '')
    this.prefill()
  },
  methods: {
    prefill() {
      const u = userStore.state.user || {}
      if (u.gender !== null && u.gender !== undefined) this.form.gender = u.gender
      if (u.ageRange) this.form.ageRange = u.ageRange
      if (u.skinType) this.form.skinType = u.skinType
      this.form.preferenceTags = normalizeTags(u.preferenceTags)
    },
    toggleTag(tag) {
      const i = this.form.preferenceTags.indexOf(tag)
      if (i >= 0) this.form.preferenceTags.splice(i, 1)
      else this.form.preferenceTags.push(tag)
    },
    prev() {
      if (this.step > 0) this.step -= 1
    },
    next() {
      if (this.isLast) {
        this.submit()
      } else {
        this.step += 1
      }
    },
    async submit() {
      if (this.loading) return
      this.loading = true
      const payload = {}
      if (this.form.gender !== null && this.form.gender !== undefined) payload.gender = this.form.gender
      if (this.form.ageRange) payload.ageRange = this.form.ageRange
      if (this.form.skinType) payload.skinType = this.form.skinType
      if (this.form.preferenceTags.length) payload.preferenceTags = this.form.preferenceTags
      try {
        if (Object.keys(payload).length) {
          const user = await updateProfile(payload)
          userStore.setUser(user)
        }
        uni.showToast({ title: '已保存', icon: 'success' })
        setTimeout(() => this.goNext(), 500)
      } catch (e) {
        this.loading = false
      }
    },
    skip() {
      this.goNext()
    },
    goNext() {
      const target = this.redirect || '/pages/product-list/product-list'
      const tabPages = ['/pages/chat/chat', '/pages/product-list/product-list', '/pages/cart/cart', '/pages/profile/profile']
      const path = target.split('?')[0]
      if (tabPages.includes(path)) uni.switchTab({ url: path })
      else uni.redirectTo({ url: target })
    }
  }
}
</script>

<style scoped>
.setup-page {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  padding: 32rpx 32rpx calc(40rpx + env(safe-area-inset-bottom));
  box-sizing: border-box;
  background: radial-gradient(circle at 90% 6%, rgba(249, 115, 22, 0.12), transparent 34%), #f4f8f8;
}
.setup-head {
  margin-bottom: 40rpx;
}
.progress-track {
  height: 12rpx;
  border-radius: 999rpx;
  background: #e6efec;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: 999rpx;
  background: linear-gradient(90deg, #0f766e, #14b8a6);
  transition: width 0.3s ease;
}
.head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 18rpx;
}
.step-index {
  color: #667085;
  font-size: 24rpx;
  font-weight: 700;
}
.skip {
  color: #98a2b3;
  font-size: 26rpx;
}
.setup-body {
  flex: 1;
}
.q-title {
  display: block;
  color: #1f2937;
  font-size: 44rpx;
  font-weight: 900;
}
.q-sub {
  display: block;
  margin-top: 14rpx;
  color: #667085;
  font-size: 27rpx;
}
.options {
  margin-top: 44rpx;
}
.option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20rpx;
  padding: 30rpx 28rpx;
  border: 2rpx solid #e4e7ec;
  border-radius: 22rpx;
  background: #ffffff;
  color: #1f2937;
  font-size: 30rpx;
  font-weight: 700;
}
.option.active {
  border-color: #14b8a6;
  background: #f0fdfa;
}
.chip-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 18rpx;
  margin-top: 44rpx;
}
.tag-scroll {
  max-height: calc(100vh - 460rpx);
  margin-top: 20rpx;
}
.tag-group {
  margin-bottom: 22rpx;
}
.group-title {
  display: block;
  margin: 14rpx 0 4rpx;
  color: #98a2b3;
  font-size: 25rpx;
  font-weight: 800;
}
.tag-group .chip-wrap {
  margin-top: 14rpx;
}
.chip {
  padding: 18rpx 30rpx;
  border: 2rpx solid #e4e7ec;
  border-radius: 999rpx;
  background: #ffffff;
  color: #344054;
  font-size: 27rpx;
  font-weight: 700;
}
.chip.active {
  border-color: #14b8a6;
  background: #14b8a6;
  color: #ffffff;
}
.setup-footer {
  display: flex;
  gap: 18rpx;
  margin-top: 28rpx;
}
.btn {
  flex: 1;
  height: 92rpx;
  border-radius: 999rpx;
  font-size: 30rpx;
  font-weight: 800;
  text-align: center;
  line-height: 92rpx;
}
.btn.ghost {
  flex: 0 0 200rpx;
  background: #ffffff;
  border: 1rpx solid #e5e7eb;
  color: #667085;
}
.btn.primary {
  background: linear-gradient(135deg, #0f766e, #14b8a6);
  color: #ffffff;
  box-shadow: 0 14rpx 30rpx rgba(20, 184, 166, 0.24);
}
.btn.primary.loading {
  opacity: 0.6;
}
</style>
