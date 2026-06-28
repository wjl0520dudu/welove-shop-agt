const state = {
  currentConversation: null,
  conversations: [],
  messages: []
}

export default {
  state,
  setCurrentConversation(conversation) {
    state.currentConversation = conversation
  },
  reset() {
    state.currentConversation = null
    state.conversations = []
    state.messages = []
  }
}
