<template>
  <view class="page chat-page">
    <view class="topbar">
      <view class="icon-btn" @tap="openDrawer">
        <uni-icons type="bars" size="22" color="#0f766e" />
      </view>
      <view class="title-wrap">
        <text class="title">{{ headerTitle }}</text>
      </view>
      <view class="icon-btn" @tap="newChat">
        <uni-icons type="plusempty" size="22" color="#0f766e" />
      </view>
    </view>

    <scroll-view
      class="messages"
      scroll-y
      :scroll-into-view="scrollIntoId"
      :scroll-with-animation="true"
    >
      <RecommendChips
        v-if="isEmpty"
        :greeting="greeting"
        :questions="recommended"
        @pick="pickRecommend"
      />
      <template v-else>
        <view v-for="msg in messages" :key="msg._localId" class="msg-block">
          <MessageBubble
            :message="msg"
            :user-initial="userInitial"
            @longpress="onMessageLongpress"
            @retry="retryMessage"
          />
          <!-- DAG execution details are persisted for diagnostics but deliberately
               not displayed in the end-user conversation. -->
          <view v-if="false" class="dag-progress">
            <view class="dag-title">多任务处理{{ msg.streaming ? '中' : '完成' }}</view>
            <view v-if="msg.agentMeta.taskLevels && msg.agentMeta.taskLevels.length" class="dag-levels">
              并行层级：{{ formatTaskLevels(msg.agentMeta.taskLevels) }}
            </view>
            <view v-for="item in dagItems(msg.agentMeta)" :key="item.task && item.task.id || item.id" class="dag-task">
              <text class="dag-status" :class="item.status || 'pending'">{{ dagStatusText(item.status) }}</text>
              <text>{{ (item.task && item.task.question) || item.question || '子任务' }}</text>
            </view>
          </view>
          <view v-if="msg.role === 'assistant'" class="cards-under">
            <ChatProductCards
              v-if="msg.productCards && msg.productCards.length"
              :products="msg.productCards"
              @open="onProductOpen"
              @add="onProductAdd"
            />
            <ConfirmCard
              v-if="msg.confirmCard"
              :card="msg.confirmCard"
              @confirm="onConfirmCard"
              @cancel="onCancelCard"
            />
            <CartSelectionCard
              v-if="msg.cartSelection"
              :card="msg.cartSelection"
              @submit="onCartSelectionSubmit"
            />
          </view>
        </view>
        <view id="msg-bottom" class="bottom-anchor"></view>
      </template>
    </scroll-view>

    <view class="input-bar">
      <!-- 待发送图片预览:选好图后先在输入框上方展示,点 × 可撤销 -->
      <view v-if="pendingImageUrl" class="pending-image">
        <image class="pending-image-thumb" :src="pendingImageUrl" mode="aspectFill" />
        <view class="pending-image-remove" @tap="removePendingImage">×</view>
        <text class="pending-image-tip">已选图片,发送后将图文一起搜索</text>
      </view>
      <view class="input-row">
        <!-- 图片选择按钮:上传中显示 loading,禁用防重复 -->
        <view
          class="image-btn"
          :class="{ disabled: uploadingImage || streaming }"
          @tap="pickImage"
        >
          <uni-icons v-if="!uploadingImage" type="image" size="22" color="#14b8a6" />
          <view v-else class="uploading-dot"></view>
        </view>
        <view class="input-wrap">
          <input
            v-model="input"
            class="chat-input"
            :placeholder="pendingImageUrl ? '可加文字描述(选填)' : '输入你的购物需求'"
            confirm-type="send"
            :adjust-position="false"
            @confirm="onSend"
          />
        </view>
        <view
          v-if="!streaming"
          class="send-btn"
          :class="{ disabled: !canSend }"
          @tap="onSend"
        >
          <uni-icons type="paperplane-filled" size="22" color="#ffffff" />
        </view>
        <view v-else class="stop-btn" @tap="stop">
          <view class="stop-square"></view>
        </view>
      </view>
    </view>

    <ConversationDrawer
      :visible="drawerVisible"
      :conversations="conversations"
      :current-id="currentConversation ? currentConversation.id : ''"
      :loading="loadingConversations"
      @close="closeDrawer"
      @new="newChat"
      @select="selectConversation"
      @rename="renameConversation"
      @pin="pinConversation"
      @delete="onDeleteConversation"
    />

    <ProductSkuSheet
      :visible="showSkuSheet"
      :skus="skuList"
      @close="showSkuSheet = false"
      @confirm="onSkuConfirm"
    />
  </view>
</template>

<script>
import { requireLoginFromProtectedTab, toLogin } from '../../utils/routeGuard'
import { supportsEventStream } from '../../utils/sse'
import { refreshAccessToken } from '../../utils/request'
import { buildRecommendedQuestions } from '../../utils/chatRecommend'
import {
  streamMessage,
  uploadChatImage,
  sendMessage,
  getMessages,
  feedback as feedbackApi,
  stopStream,
  updateConversation as updateConversationApi,
  deleteConversation as deleteConversationApi
} from '../../api/chat'
import { getProductSkus } from '../../api/product'
import { addCart } from '../../api/cart'
import userStore from '../../store/user'
import cartStore from '../../store/cart'
import chatStore from '../../store/chat'

import MessageBubble from '../../components/chat/MessageBubble.vue'
import ChatProductCards from '../../components/chat/ChatProductCards.vue'
import ConfirmCard from '../../components/chat/ConfirmCard.vue'
import CartSelectionCard from '../../components/chat/CartSelectionCard.vue'
import ConversationDrawer from '../../components/chat/ConversationDrawer.vue'
import RecommendChips from '../../components/chat/RecommendChips.vue'
import ProductSkuSheet from '../../components/ProductSkuSheet.vue'

export default {
  components: {
    MessageBubble,
    ChatProductCards,
    ConfirmCard,
    CartSelectionCard,
    ConversationDrawer,
    RecommendChips,
    ProductSkuSheet
  },
  data() {
    return {
      input: '',
      messages: [],
      conversations: [],
      currentConversation: null,
      streaming: false,
      loadingConversations: false,
      drawerVisible: false,
      showSkuSheet: false,
      skuList: [],
      pendingCartProductId: null,
      recommended: [],
      learnedRecommended: [],
      scrollIntoId: '',
      /** 记录当前正在 SSE 流的会话 ID，用于切换窗口后其他会话收到消息时标红点 */
      _streamingConvId: null,
      /** 待发送的图片 URL(用户已选图并上传完成,尚未跟 content 一起发送) */
      pendingImageUrl: '',
      /** 是否正在上传图(禁用发送按钮和图片按钮避免重复) */
      uploadingImage: false
    }
  },
  computed: {
    isEmpty() {
      return !this.messages.length
    },
    headerTitle() {
      return (this.currentConversation && this.currentConversation.title) || 'AI 导购'
    },
    userInitial() {
      const name = userStore.state.user && userStore.state.user.username
      return name ? String(name).charAt(0).toUpperCase() : '我'
    },
    greeting() {
      const name = userStore.state.user && userStore.state.user.username
      return name ? `你好 ${name}，我是你的专属导购助手` : '你好，我是你的专属导购助手'
    },
    /**
     * 发送按钮可用条件:
     * - 有文字 → 可发
     * - 有图 → 可发(允许纯图搜索)
     * - 都没有 → 禁用
     */
    canSend() {
      return this.input.trim().length > 0 || !!this.pendingImageUrl
    }
  },
  onShow() {
    if (!requireLoginFromProtectedTab('/pages/chat/chat')) return
    userStore.restore()
    this.buildRecommended()
    // 快照会话内存缓存到响应式副本
    this.conversations = [...chatStore.state.conversations]
    this.currentConversation = chatStore.state.currentConversation
    const currentId = this.currentConversation && this.currentConversation.id
    this.messages = (currentId && chatStore.getConversationMessages(currentId)) || chatStore.state.messages
    this.streaming = currentId ? chatStore.isStreaming(currentId) : false
    chatStore.setMessages(this.messages)
    if (!this.conversations.length) {
      this.loadConversations()
    }
    this.scrollToBottom()
  },
  onHide() {
    // 不再在 onHide 中 abort——切换窗口时 SSE 应在后台继续接收，
    // 与豆包行为一致。只有点击停止按钮才会断开当前会话的流。
  },
  onUnload() {
    // Keep in-flight SSE tasks alive unless the user taps stop.
  },
  methods: {
    /* ---------- 会话列表 ---------- */
    async loadConversations() {
      this.loadingConversations = true
      try {
        const list = await chatStore.loadConversations()
        this.conversations = [...list]
      } catch (e) {
        // 静默失败，空态兜底
      } finally {
        this.loadingConversations = false
      }
    },
    openDrawer() {
      this.drawerVisible = true
      if (!this.conversations.length) this.loadConversations()
    },
    closeDrawer() {
      this.drawerVisible = false
    },
    async selectConversation(conv) {
      this.closeDrawer()
      // 切换会话只切换视图，旧会话的 SSE 继续写入自己的会话缓存。
      this.saveCurrentConversationMessages()
      chatStore.clearNewMessage(conv.id)
      try {
        this.currentConversation = conv
        chatStore.setCurrentConversation(conv)
        const cached = chatStore.getConversationMessages(conv.id)
        if (cached) {
          this.messages = cached
        } else {
          await chatStore.openConversation(conv)
          this.messages = (chatStore.state.messages || []).map((m) => this.hydrateServerMessage(m))
          chatStore.setConversationMessages(conv.id, this.messages)
        }
        chatStore.setMessages(this.messages)
        this.syncCurrentStreaming()
        this.scrollToBottom()
      } catch (e) {
        uni.showToast({ title: '加载会话失败', icon: 'none' })
      }
    },
    async newChat() {
      this.saveCurrentConversationMessages()
      this.currentConversation = null
      this.messages = []
      this.streaming = false
      chatStore.setCurrentConversation(null)
      chatStore.setMessages(this.messages)
      this.buildRecommended()
      this.closeDrawer()
    },
    renameConversation(conv) {
      uni.showModal({
        title: '重命名会话',
        editable: true,
        placeholderText: conv.title || '新对话',
        success: async (res) => {
          const title = res.confirm && res.content ? res.content.trim() : ''
          if (!title) return
          try {
            await updateConversationApi(conv.id, { title })
            conv.title = title
            this.conversations = [...this.conversations]
            chatStore.setConversations(this.conversations)
          } catch (e) {
            uni.showToast({ title: '重命名失败', icon: 'none' })
          }
        }
      })
    },
    async pinConversation(conv) {
      const next = conv.isPinned ? 0 : 1
      try {
        await updateConversationApi(conv.id, { isPinned: next })
        conv.isPinned = next
        this.conversations = [...this.conversations]
        chatStore.setConversations(this.conversations)
      } catch (e) {
        uni.showToast({ title: '操作失败', icon: 'none' })
      }
    },
    onDeleteConversation(conv) {
      uni.showModal({
        title: '删除会话',
        content: '确定删除该会话吗？删除后不可恢复。',
        success: async (res) => {
          if (!res.confirm) return
          try {
            await deleteConversationApi(conv.id)
            this.conversations = this.conversations.filter((c) => String(c.id) !== String(conv.id))
            chatStore.setConversations(this.conversations)
            if (this.currentConversation && String(this.currentConversation.id) === String(conv.id)) {
              this.newChat()
            }
          } catch (e) {
            uni.showToast({ title: '删除失败', icon: 'none' })
          }
        }
      })
    },

    /* ---------- 发送与流式 ---------- */
    onSend() {
      this.send()
    },
    pickRecommend(question) {
      this.send(question)
    },
    /**
     * 用户点图片按钮:选一张图 → 立即上传到 chat-service → 存 pendingImageUrl。
     * 使用统一的 pendingImageUrl 状态,后续 send 时判断是否走多模态入口。
     */
    async pickImage() {
      if (this.uploadingImage || this.streaming) return
      try {
        const chooseRes = await new Promise((resolve, reject) => {
          uni.chooseImage({
            count: 1,
            sizeType: ['compressed'],  // H5 下会被 uni 尽量压缩
            sourceType: ['album', 'camera'],
            success: resolve,
            fail: reject
          })
        })
        const filePath = chooseRes && chooseRes.tempFilePaths && chooseRes.tempFilePaths[0]
        if (!filePath) return
        this.uploadingImage = true
        uni.showLoading({ title: '上传中', mask: true })
        try {
          const { url } = await uploadChatImage(filePath)
          if (!url) throw new Error('上传返回空 URL')
          this.pendingImageUrl = url
        } finally {
          this.uploadingImage = false
          uni.hideLoading()
        }
      } catch (err) {
        // chooseImage fail (用户取消 / 权限拒绝) 不弹提示;上传失败才提示
        const msg = err && err.errMsg
        if (msg && msg.indexOf('chooseImage:fail') === 0) return
        uni.showToast({ title: (err && err.message) || '图片上传失败', icon: 'none' })
      }
    },
    /** 撤销待发送图片(点缩略图右上角 ×) */
    removePendingImage() {
      this.pendingImageUrl = ''
    },
    async send(text) {
      const content = (text != null ? text : this.input).trim()
      const imageUrl = this.pendingImageUrl
      const hasImage = !!imageUrl
      // 纯文本时必须有 content;有图时 content 可空(纯图搜索)
      if (!content && !hasImage) {
        uni.showToast({ title: '请输入内容或选择图片', icon: 'none' })
        return
      }
      if (this.streaming) return
      this.input = ''
      // 发出去后立即清 pending,防止重复带图
      this.pendingImageUrl = ''

      // 用户消息:有图时 content 允许为空,由 MessageBubble 渲染 imageUrl + 文本
      const userMsg = this.makeMessage({
        role: 'user',
        content: content || (hasImage ? '' : ''),
        imageUrl: hasImage ? imageUrl : undefined
      })
      this.messages.push(userMsg)
      this.scrollToBottom()

      let conv
      try {
        // 标题用文本;纯图搜索用"[图片]"
        conv = await chatStore.ensureConversation(this.titleFrom(content || '[图片]'))
        this.currentConversation = conv
        this.conversations = [...chatStore.state.conversations]
        chatStore.setConversationMessages(conv.id, this.messages)
      } catch (e) {
        uni.showToast({ title: '创建会话失败', icon: 'none' })
        return
      }

      const assistant = this.makeMessage({ role: 'assistant', content: '', pending: true, streaming: true })
      this.messages.push(assistant)
      // Vue3: push 进响应式数组后，须取回数组内的响应式代理再改，
      // 否则改的是裸对象引用，不会触发重渲染（流式 token 收到了但聊天框不刷新）。
      const reactiveAssistant = this.messages[this.messages.length - 1]
      chatStore.setConversationMessages(conv.id, this.messages)
      this.setStreaming(true)
      this.scrollToBottom()

      await this.runStream(conv.id, content, reactiveAssistant, true, false, hasImage ? imageUrl : '')
    },
    async runStream(conversationId, content, assistant, allowAuthRetry, retry = false, imageUrl = '') {
      this._streamingConvId = conversationId
      if (!supportsEventStream()) {
        if (imageUrl) {
          assistant.pending = false
          assistant.streaming = false
          assistant.errored = true
          uni.showToast({ title: '当前环境不支持图片检索', icon: 'none' })
          return
        }
        const ok = await this.fallbackSend(conversationId, content, assistant)
        if (!ok) this.markErrored(assistant, conversationId)
        return
      }

      const payload = this.buildPayload(conversationId, content, retry, imageUrl)
      let gotText = false
      let streamError = null
      const callbacks = {
        onText: (delta) => {
          if (!delta) return
          assistant.pending = false
          assistant.content += delta
          gotText = true
          this.scrollToBottom()
        },
        onProductCards: (list) => { assistant.productCards = list || []; this.scrollToBottom() },
        onConfirm: (card) => { assistant.confirmCard = card || null; this.scrollToBottom() },
        onCartSelection: (card) => { assistant.cartSelection = card || null; this.scrollToBottom() },
        onRouted: (t) => { assistant.taskType = t || '' },
        // The plan and subtask events are diagnostic telemetry, not chat UI.
        onOrchestratorPlan: () => {},
        onOrchestratorSubtask: () => {},
        // final 兜底：若某类回复没有逐 token 流（如 unknown/error 静态回复），用 final 的完整答案补上
        onFinalText: (text, finalPayload = {}) => {
          const finalTaskType = finalPayload.task_type || finalPayload.taskType || assistant.taskType
          const isOrchestratorFinal = finalTaskType === 'orchestrator'
          const suggested = finalPayload.suggested_questions || finalPayload.suggestedQuestions || []
          if (Array.isArray(suggested) && suggested.length) {
            this.learnedRecommended = suggested.filter(Boolean)
            this.buildRecommended()
          }
          if (finalTaskType === 'orchestrator') {
            assistant.agentMeta = {
              ...(assistant.agentMeta || {}),
              orchestratorMode: finalPayload.orchestrator_mode || 'complex',
              orchestratorReason: finalPayload.orchestrator_reason || '',
              subQuestions: finalPayload.sub_questions || [],
              subResults: finalPayload.sub_results || [],
              taskLevels: finalPayload.task_levels || []
            }
          }
          // Orchestrator 会先流出子任务标题/子答案，final.answer 才是完整聚合结果。
          // 不能因为 gotText=true 就丢弃 final，否则前端只能看到拆解标题。
          if (text && (isOrchestratorFinal || !gotText)) {
            assistant.pending = false
            assistant.content = text
            gotText = true
            this.scrollToBottom()
          }
        },
        onDone: (data) => {
          this.finishStream(assistant, data, conversationId)
          // SSE 开始时的会话与当前会话不一致 → 用户已切走到其他窗口/会话
          if (this.currentConversation && String(this.currentConversation.id) !== String(conversationId)) {
            chatStore.markNewMessage(conversationId)
          }
        },
        onError: (error) => {
          // 注意:AbortError 路径不会走这里——chat.vue 已在 runStream 的 catch 里显式 return。
          // 走到 onError 一定是后端真正发了 error 事件(LLM 异常 / ai-service 5xx 等)。
          assistant.pending = false
          assistant.streaming = false
          if (!assistant.content) {
            // 没有任何 token 才标 errored,提示用户「回复中断」
            assistant.errored = true
          }
          streamError = error || { message: '回复失败' }
          this.syncCurrentStreaming()
        }
      }

      const streamRecord = chatStore.startStream(conversationId, {
        assistant,
        messages: this.messages,
        userAborted: false,
        status: 'streaming'
      })
      this.syncCurrentStreaming()

      // The main stream endpoint accepts an optional imageUrl and selects the
      // text-only, image-only, or text-image retrieval path on the backend.
      const handle = streamMessage(payload, callbacks)
      if (streamRecord) streamRecord.handle = handle
      this.streamHandle = handle
      try {
        await handle.promise
        if (streamError) {
          if (imageUrl) {
            const message = streamError.message || streamError.content || '图片检索失败，请更换图片后重试'
            uni.showToast({ title: String(message).slice(0, 40), icon: 'none' })
          }
          this.markErrored(assistant, conversationId)
        } else if (assistant.streaming) {
          this.finishStream(assistant, {}, conversationId)
        }
      } catch (err) {
        if (err && err.name === 'AbortError') {
          // 用户主动中止:保留已收 token,标 stopped,主动把半成品发给后端落库。
          // 网络通时由 stopStream 写库;网络断时由后端 Flux.doOnCancel 兜底;SQL 去重避免重复。
          const record = chatStore.getStream(conversationId)
          assistant.pending = false
          assistant.streaming = false
          if (record && record.userAborted) {
            assistant.stopped = true
            assistant.stoppedReason = 'user_abort'
            this.persistStoppedSnapshot(conversationId, assistant)
          } else if (!assistant.content) {
            assistant.errored = true
          }
          return
        }
        if ((err && (err.status === 401 || err.status === 403)) && allowAuthRetry && !gotText) {
          const refreshed = await refreshAccessToken().catch(() => false)
          if (refreshed) {
            return this.runStream(conversationId, content, assistant, false, false, imageUrl)
          }
          this.syncCurrentStreaming()
          toLogin('/pages/chat/chat')
          return
        }
        if (!gotText && !imageUrl) {
          const ok = await this.fallbackSend(conversationId, content, assistant)
          if (ok) return
        }
        if (imageUrl) {
          uni.showToast({ title: '图片检索失败，请更换图片后重试', icon: 'none' })
        }
        this.markErrored(assistant, conversationId)
      } finally {
        chatStore.finishStream(conversationId)
        chatStore.setConversationMessages(conversationId, streamRecord && streamRecord.messages ? streamRecord.messages : this.messages)
        this.syncCurrentStreaming()
        if (this.streamHandle === handle) this.streamHandle = null
      }
    },
    async fallbackSend(conversationId, content, assistant) {
      try {
        const user = userStore.state.user || {}
        const msg = await sendMessage({ userId: Number(user.id) || undefined, conversationId, content })
        assistant.pending = false
        assistant.content = (msg && msg.content) || ''
        assistant.id = msg && msg.id
        assistant.productCards = (msg && msg.productCards) || []
        assistant.confirmCard = (msg && msg.confirmCard) || null
        assistant.cartSelection = (msg && msg.cartSelection) || null
        assistant.streaming = false
        if (this.isCurrentConversation(conversationId)) this.streaming = false
        this.scrollToBottom()
        return Boolean(assistant.content || assistant.productCards.length)
      } catch (e) {
        return false
      }
    },
    async finishStream(assistant, data, conversationId) {
      assistant.pending = false
      assistant.streaming = false
      if (data && data.messageId) assistant.id = data.messageId
      if (this.isCurrentConversation(conversationId)) this.streaming = false
      if (!assistant.id) {
        try {
          const list = await getMessages(conversationId)
          const arr = Array.isArray(list) ? list : (list && list.records) || []
          for (let i = arr.length - 1; i >= 0; i--) {
            if (arr[i].role === 'assistant') { assistant.id = arr[i].id; break }
          }
        } catch (e) {
          // 拿不到 id 时，反馈按钮将不可用，静默即可
        }
      }
    },
    markErrored(assistant, conversationId) {
      assistant.pending = false
      assistant.streaming = false
      if (!assistant.content) assistant.errored = true
      if (!conversationId || this.isCurrentConversation(conversationId)) this.streaming = false
    },
    stop() {
      this.abortStream(true)
    },
    abortStream(userInitiated = false, conversationId) {
      const id = conversationId || (this.currentConversation && this.currentConversation.id)
      const record = id ? chatStore.getStream(id) : null
      if (record) {
        record.userAborted = Boolean(userInitiated)
        if (record.handle) record.handle.abort()
        return
      }
      if (this.streamHandle && userInitiated) {
        this.streamHandle.abort()
      }
    },
    /**
     * 把当前 assistant 半成品快照发给后端落库(status=truncated)。
     * 仅在前端 AbortError 路径调用;失败也不抛错(后端 doOnCancel 会兜底)。
     */
    persistStoppedSnapshot(conversationId, assistant) {
      if (!conversationId) return
      const payload = {
        conversationId,
        content: assistant.content || '',
        productCards: assistant.productCards && assistant.productCards.length ? assistant.productCards : null,
        confirmCard: assistant.confirmCard || null,
        cartSelection: assistant.cartSelection || null,
        taskType: assistant.taskType || '',
        clientTs: Date.now()
      }
      stopStream(payload)
        .then((messageId) => {
          if (messageId) assistant.id = messageId
        })
        .catch(() => {
          // 静默失败,后端 Flux.doOnCancel 已兜底,UI 不阻塞
        })
    },
    async retryMessage(message) {
      if (this.streaming) return
      // 用 _localId 定位原消息:MessageBubble emit 出来的可能是 chatStore 里的引用,
      // 而 this.messages 在 selectConversation 时被 map(hydrate) 重新创建,引用对比必失败。
      const localId = message && message._localId
      const target = (localId ? this.messages.find((m) => m._localId === localId) : null) || message
      const idx = this.messages.indexOf(target)
      let userContent = ''
      for (let i = idx - 1; i >= 0; i--) {
        if (this.messages[i].role === 'user') { userContent = this.messages[i].content; break }
      }
      if (!userContent) {
        console.warn('[retry] no preceding user message found, abort retry', { localId, idx, msgCount: this.messages.length })
        uni.showToast({ title: '找不到原始问题,无法重发', icon: 'none' })
        return
      }
      const conversationId = this.currentConversation && this.currentConversation.id
      if (!conversationId) {
        console.warn('[retry] no current conversation, abort retry')
        uni.showToast({ title: '会话已失效,请刷新页面', icon: 'none' })
        return
      }
      console.log('[retry] start', { localId, conversationId, userContent: userContent.slice(0, 30) })
      target.errored = false
      target.stopped = false
      target.stoppedReason = ''
      target.pending = true
      target.streaming = true
      target.content = ''
      target.productCards = []
      target.confirmCard = null
      target.cartSelection = null
      target.id = null
      target.taskType = ''
      this.setStreaming(true)
      this.scrollToBottom()
      try {
        await this.runStream(conversationId, userContent, target, true, true)
        console.log('[retry] runStream resolved')
      } catch (e) {
        console.error('[retry] runStream rejected', e)
        // 出错时确保 UI 状态能恢复,避免卡在 streaming=true
        target.streaming = false
        target.pending = false
        this.setStreaming(false)
        uni.showToast({ title: '重发失败,请稍后再试', icon: 'none' })
      }
    },

    /* ---------- 商品卡 / 加购 ---------- */
    onProductOpen(product) {
      const id = product.id || product.productId || product.product_id
      if (id) uni.navigateTo({ url: `/pages/product-detail/product-detail?id=${id}` })
    },
    async onProductAdd(product) {
      const productId = product.id || product.productId || product.product_id
      if (!productId) return
      this.pendingCartProductId = productId
      try {
        const skus = await getProductSkus(productId)
        this.skuList = Array.isArray(skus) ? skus : []
      } catch (e) {
        this.skuList = []
      }
      if (this.skuList.length) {
        this.showSkuSheet = true
      } else {
        this.addToCart(productId, null)
      }
    },
    onSkuConfirm(sku) {
      this.showSkuSheet = false
      this.addToCart(this.pendingCartProductId, sku && sku.id)
    },
    async addToCart(productId, skuId) {
      try {
        await addCart(productId, skuId)
        cartStore.bump(1)
        cartStore.loadCart().catch(() => {})
        uni.showToast({ title: '已加入购物车', icon: 'success' })
      } catch (e) {
        uni.showToast({ title: '加入购物车失败', icon: 'none' })
      }
    },
    async onCartSelectionSubmit(items) {
      if (!items || !items.length) return
      uni.showLoading({ title: '加入中…', mask: true })
      let ok = 0
      for (const it of items) {
        try {
          await addCart(it.productId || it.id, it.skuId || null)
          ok += 1
        } catch (e) {
          // 单件失败不阻断其余
        }
      }
      if (ok) cartStore.bump(ok)
      cartStore.loadCart().catch(() => {})
      uni.hideLoading()
      uni.showToast({ title: ok ? `已加入 ${ok} 件` : '加入失败', icon: ok ? 'success' : 'none' })
    },
    syncBadge(count) {
      return cartStore.syncBadge(count)
    },

    /* ---------- 确认卡 / 反馈 ---------- */
    onConfirmCard(card) {
      this.send(card.confirmValue || card.confirmText || '确认')
    },
    onCancelCard(card) {
      this.send(card.cancelValue || card.cancelText || '再想想')
    },
    onMessageLongpress(message) {
      const items = ['复制']
      const canFeedback = message.role === 'assistant' && message.id
      if (canFeedback) items.push('赞', '踩')
      uni.showActionSheet({
        itemList: items,
        success: (res) => {
          const label = items[res.tapIndex]
          if (label === '复制') {
            uni.setClipboardData({ data: message.content || '', success: () => uni.showToast({ title: '已复制', icon: 'none' }) })
          } else if (label === '赞') {
            this.doFeedback(message, 'like')
          } else if (label === '踩') {
            this.doFeedback(message, 'dislike')
          }
        }
      })
    },
    async doFeedback(message, type) {
      try {
        await feedbackApi(message.id, type)
        message.feedbackType = type
      } catch (e) {
        uni.showToast({ title: '反馈失败', icon: 'none' })
      }
    },

    /* ---------- 工具 ---------- */
    setStreaming(v) {
      this.streaming = v
    },
    syncCurrentStreaming() {
      const id = this.currentConversation && this.currentConversation.id
      this.streaming = id ? chatStore.isStreaming(id) : false
    },
    isCurrentConversation(conversationId) {
      return Boolean(this.currentConversation && String(this.currentConversation.id) === String(conversationId))
    },
    saveCurrentConversationMessages() {
      const id = this.currentConversation && this.currentConversation.id
      if (id) chatStore.setConversationMessages(id, this.messages)
    },
    buildRecommended() {
      this.recommended = buildRecommendedQuestions(userStore.state.user || {}, {
        limit: 4,
        learnedQuestions: this.learnedRecommended
      })
    },
    buildPayload(conversationId, content, retry = false, imageUrl = '') {
      const u = userStore.state.user || {}
      const payload = {
        userId: Number(u.id) || undefined,
        conversationId,
        content,
        username: u.username || 'user',
        isAdmin: false,
        gender: u.gender,
        skinType: u.skinType,
        preferenceTags: this.normalizeTags(u.preferenceTags),
        retry
      }
      // 有图时加 imageUrl,后端 MultimodalStreamChatRequest DTO 会解析。
      // 纯文本请求不带此字段,兼容旧 StreamChatRequest。
      if (imageUrl) payload.imageUrl = imageUrl
      return payload
    },
    normalizeTags(tags) {
      if (!tags) return []
      if (Array.isArray(tags)) return tags.filter(Boolean)
      return String(tags).split(/[,，、\s]+/).filter(Boolean)
    },
    titleFrom(content) {
      const text = String(content).trim()
      return text.length > 16 ? `${text.slice(0, 16)}…` : text
    },
    makeMessage(fields) {
      this._seq = (this._seq || 0) + 1
      return {
        _localId: `l${this._seq}`,
        id: null,
        role: 'assistant',
        content: '',
        imageUrl: '',
        productCards: [],
        confirmCard: null,
        cartSelection: null,
        taskType: '',
        agentMeta: null,
        feedbackType: '',
        pending: false,
        streaming: false,
        errored: false,
        stopped: false,
        stoppedReason: '',
        ...fields
      }
    },
    hydrateServerMessage(m) {
      // 后端 status='truncated' 在前端映射为 stopped,刷新/切回时仍能看到「已停止」标签
      const isTruncated = m.status === 'truncated'
      return {
        _localId: `s${m.id}`,
        id: m.id,
        conversationId: m.conversationId,
        role: m.role,
        content: m.content || '',
        // 后端 Java 实体通常返回 imageUrl，兼容历史/代理返回的 image_url。
        imageUrl: m.imageUrl || m.image_url || '',
        productCards: m.productCards || [],
        confirmCard: m.confirmCard || null,
        cartSelection: m.cartSelection || null,
        taskType: m.taskType || '',
        agentMeta: m.agentMeta || m.agent_meta || null,
        feedbackType: m.feedbackType || '',
        pending: false,
        streaming: false,
        errored: false,
        stopped: isTruncated,
        stoppedReason: isTruncated ? (m.stoppedReason || 'user_abort') : ''
      }
    },
    scrollToBottom() {
      if (this._scrollScheduled) return
      this._scrollScheduled = true
      setTimeout(() => {
        this._scrollScheduled = false
        this.scrollIntoId = ''
        this.$nextTick(() => { this.scrollIntoId = 'msg-bottom' })
      }, 80)
    },
    dagStatusText(status) {
      const labels = { success: '已完成', failed: '失败', blocked: '已阻塞', timeout: '超时', pending: '等待中' }
      return labels[status] || '处理中'
    },
    dagItems(agentMeta = {}) {
      const events = Array.isArray(agentMeta.subtaskEvents) ? agentMeta.subtaskEvents : []
      return events.length ? events : (Array.isArray(agentMeta.subResults) ? agentMeta.subResults : [])
    },
    formatTaskLevels(levels) {
      return Array.isArray(levels) ? levels.map(level => Array.isArray(level) ? level.join('、') : '').filter(Boolean).join(' → ') : ''
    }
  }
}
</script>

<style scoped>
.chat-page {
  min-height: 100vh;
  padding-bottom: 224rpx;
  background: #f4f8f8;
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(16rpx + env(safe-area-inset-top)) 22rpx 16rpx;
  background: rgba(244, 248, 248, 0.94);
  backdrop-filter: blur(8px);
}
.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 68rpx;
  height: 68rpx;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 6rpx 16rpx rgba(15, 118, 110, 0.08);
}
.title-wrap {
  flex: 1;
  overflow: hidden;
  text-align: center;
}
.title {
  overflow: hidden;
  color: #0f766e;
  font-size: 30rpx;
  font-weight: 800;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.messages {
  height: calc(100vh - 300rpx);
  padding: 8rpx 24rpx 0;
  box-sizing: border-box;
}
.msg-block {
  margin-bottom: 4rpx;
}
.cards-under {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  margin: -12rpx 0 26rpx 78rpx;
}
.dag-progress {
  margin: 10rpx 0 18rpx 78rpx;
  padding: 16rpx 18rpx;
  border-radius: 14rpx;
  background: #ecfdf5;
  border: 1rpx solid #a7f3d0;
  color: #166534;
  font-size: 23rpx;
}
.dag-title { font-weight: 700; }
.dag-levels { margin-top: 6rpx; color: #047857; }
.dag-task { display: flex; gap: 10rpx; margin-top: 8rpx; }
.dag-status { min-width: 72rpx; color: #0f766e; }
.dag-status.failed, .dag-status.timeout, .dag-status.blocked { color: #dc2626; }
.bottom-anchor {
  height: 8rpx;
}
.input-bar {
  position: fixed;
  right: 0;
  bottom: 112rpx;
  left: 0;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  padding: 18rpx 24rpx calc(18rpx + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.98);
  border-top: 1rpx solid #e5e7eb;
  box-shadow: 0 -8rpx 28rpx rgba(15, 118, 110, 0.08);
  z-index: 20;
}
/* 输入行:图片按钮 + 输入框 + 发送按钮,横向排列 */
.input-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
/* 图片选择按钮:与发送按钮同样的圆角,配色用浅色底 + 主色图标 */
.image-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 78rpx;
  height: 78rpx;
  border-radius: 50%;
  background: #ecfdf5;
  border: 1rpx solid #a7f3d0;
  flex-shrink: 0;
}
.image-btn.disabled {
  opacity: 0.5;
}
.uploading-dot {
  width: 24rpx;
  height: 24rpx;
  border-radius: 50%;
  border: 4rpx solid #14b8a6;
  border-top-color: transparent;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
/* 待发送图片预览区:输入行上方一条,显示缩略图 + 撤销按钮 + 提示文案 */
.pending-image {
  display: flex;
  align-items: center;
  gap: 14rpx;
  padding: 12rpx 16rpx;
  background: #f0fdf4;
  border: 1rpx dashed #86efac;
  border-radius: 14rpx;
}
.pending-image-thumb {
  width: 90rpx;
  height: 90rpx;
  border-radius: 10rpx;
  background: #d1fae5;
  flex-shrink: 0;
}
.pending-image-remove {
  width: 40rpx;
  height: 40rpx;
  line-height: 40rpx;
  text-align: center;
  border-radius: 50%;
  background: #ffffff;
  color: #64748b;
  font-size: 32rpx;
  font-weight: 700;
  flex-shrink: 0;
}
.pending-image-tip {
  flex: 1;
  color: #059669;
  font-size: 24rpx;
}
.input-wrap {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex: 1;
  min-width: 0;
  height: 78rpx;
  padding: 0 24rpx;
  border-radius: 999rpx;
  background: #f4f8f8;
  border: 1rpx solid #dbe5e3;
}
.chat-input {
  flex: 1;
  height: 78rpx;
  font-size: 28rpx;
}
.send-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 78rpx;
  height: 78rpx;
  border-radius: 50%;
  background: linear-gradient(135deg, #0f766e, #14b8a6);
  box-shadow: 0 10rpx 24rpx rgba(20, 184, 166, 0.28);
}
.send-btn.disabled {
  background: #cbd5e1;
  box-shadow: none;
}
.stop-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 78rpx;
  height: 78rpx;
  border-radius: 50%;
  background: #ef4444;
  box-shadow: 0 10rpx 24rpx rgba(239, 68, 68, 0.28);
}
.stop-square {
  width: 26rpx;
  height: 26rpx;
  border-radius: 6rpx;
  background: #ffffff;
}
</style>
