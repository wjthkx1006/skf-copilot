import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import './App.css'

// Dify API 配置
const API_KEY = 'app-aiKkdUntwqNNX7OZIzeTlbQY'
const BASE_URL = 'https://api.dify.ai/v1'

// Auth API
const AUTH_BASE_URL = '/api/auth'

function App() {
  // Auth state
  const [user, setUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [authToken, setAuthToken] = useState(null)

  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hello! How can I help you with your issue today?', time: new Date() }
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const [theme, setTheme] = useState('dark')
  const [conversations, setConversations] = useState([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [agentStatus, setAgentStatus] = useState(null)
  const [showHistoryModal, setShowHistoryModal] = useState(false)
  const [historySearch, setHistorySearch] = useState('')
  const [renamingConv, setRenamingConv] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  // Bot mode: 'dify' = IT Helpdesk (Dify cloud), 'skf' = SKF Copilot (local RAG)
  const [botMode, setBotMode] = useState('dify')
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const modalRef = useRef(null)

  // Get user ID from auth or fallback
  const USER_ID = user?.email || 'web-user-001'

  // Check for token in URL (after SAML redirect)
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search)
    const token = urlParams.get('token')
    
    if (token) {
      // Store token and clean URL
      localStorage.setItem('auth_token', token)
      setAuthToken(token)
      window.history.replaceState({}, document.title, window.location.pathname)
    } else {
      // Check for existing token
      const storedToken = localStorage.getItem('auth_token')
      if (storedToken) {
        setAuthToken(storedToken)
      }
    }
  }, [])

  // Verify token and get user info
  useEffect(() => {
    const verifyAuth = async () => {
      if (!authToken) {
        setAuthLoading(false)
        return
      }

      try {
        const response = await fetch(`${AUTH_BASE_URL}/verify?token=${authToken}`)
        const data = await response.json()
        
        if (data.valid) {
          setUser(data.user)
        } else {
          // Token invalid, clear it
          localStorage.removeItem('auth_token')
          setAuthToken(null)
        }
      } catch (error) {
        console.error('Auth verification failed:', error)
      } finally {
        setAuthLoading(false)
      }
    }

    verifyAuth()
  }, [authToken])

  // Login handler
  const handleLogin = useCallback(() => {
    window.location.href = `${AUTH_BASE_URL}/saml/login`
  }, [])

  // Logout handler
  const handleLogout = useCallback(() => {
    localStorage.removeItem('auth_token')
    setAuthToken(null)
    setUser(null)
    window.location.href = `${AUTH_BASE_URL}/saml/logout`
  }, [])

  const quickActions = [
    'What is the purpose and scope of this SOP?',
    'What are the key stages in the Helpdesk process?',
    'What are the four priority levels for tickets?',
    'What are the three levels of escalation?',
    'How often should P1 issues get status updates?'
  ]

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, agentStatus])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  // Close modal when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (modalRef.current && !modalRef.current.contains(e.target)) {
        setShowHistoryModal(false)
      }
    }
    if (showHistoryModal) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showHistoryModal])

  // Fetch conversations when modal opens
  useEffect(() => {
    if (showHistoryModal) {
      fetchConversations()
    }
  }, [showHistoryModal])

  const fetchConversations = async () => {
    setLoadingHistory(true)
    try {
      const response = await fetch(`${BASE_URL}/conversations?user=${USER_ID}&limit=50`, {
        headers: { 'Authorization': `Bearer ${API_KEY}` }
      })
      if (response.ok) {
        const data = await response.json()
        setConversations(data.data || [])
      }
    } catch (error) {
      console.error('Failed to fetch conversations:', error)
    } finally {
      setLoadingHistory(false)
    }
  }

  const fetchMessages = async (convId) => {
    setShowHistoryModal(false)
    setIsLoading(true)
    try {
      const response = await fetch(`${BASE_URL}/messages?user=${USER_ID}&conversation_id=${convId}&limit=100`, {
        headers: { 'Authorization': `Bearer ${API_KEY}` }
      })
      if (response.ok) {
        const data = await response.json()
        const formattedMsgs = []
        // API returns messages in chronological order (oldest first)
        const messagesData = data.data || []
        for (const msg of messagesData) {
          if (msg.query) {
            formattedMsgs.push({
              role: 'user',
              content: msg.query,
              time: new Date(msg.created_at * 1000),
              id: msg.id + '-q'
            })
          }
          if (msg.answer) {
            formattedMsgs.push({
              role: 'assistant',
              content: msg.answer,
              time: new Date(msg.created_at * 1000),
              id: msg.id + '-a'
            })
          }
        }
        setMessages(formattedMsgs)
        setConversationId(convId)
      }
    } catch (error) {
      console.error('Failed to fetch messages:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const deleteConversation = async (convId, e) => {
    e.stopPropagation()
    e.preventDefault()
    
    // Optimistic UI - remove immediately
    setConversations(prev => prev.filter(c => c.id !== convId))
    
    try {
      await fetch(`${BASE_URL}/conversations/${convId}?user=${USER_ID}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${API_KEY}` }
      })
      if (conversationId === convId) {
        startNewChat()
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error)
      fetchConversations()
    }
  }

  const renameConversation = async (convId) => {
    if (!renameValue.trim()) {
      setRenamingConv(null)
      return
    }
    try {
      const response = await fetch(`${BASE_URL}/conversations/${convId}/name?user=${USER_ID}`, {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name: renameValue })
      })
      if (response.ok) {
        setConversations(prev => prev.map(c => 
          c.id === convId ? { ...c, name: renameValue } : c
        ))
      }
    } catch (error) {
      console.error('Failed to rename conversation:', error)
    } finally {
      setRenamingConv(null)
      setRenameValue('')
    }
  }

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark')
  }

  // Guardrail check function
  const checkGuardrail = async (text) => {
    try {
      const response = await fetch('/api/guardrail/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      })
      if (response.ok) {
        return await response.json()
      }
    } catch (e) {
      console.error('Guardrail check failed:', e)
    }
    return { safe: true, blocked: false } // Fail open if check fails
  }

  const sendMessage = async (text, modeOverride) => {
    const activeMode = modeOverride || botMode
    const userMessage = text || input.trim()
    if (!userMessage || isLoading) return

    setInput('')
    setIsLoading(true)
    setAgentStatus('thinking')

    setMessages(prev => [...prev, { role: 'user', content: userMessage, time: new Date() }])

    const aiMessageId = Date.now()
    setMessages(prev => [...prev, { role: 'assistant', content: '', id: aiMessageId, time: new Date() }])

    try {
      // Guardrail pre-check before sending to Dify
      const guardrailResult = await checkGuardrail(userMessage)
      if (guardrailResult.blocked) {
        // Content blocked by guardrail
        const blockedMessage = guardrailResult.message || '⚠️ 您的输入包含不当内容，请重新表述。'
        setMessages(prev =>
          prev.map(msg =>
            msg.id === aiMessageId
              ? { ...msg, content: blockedMessage }
              : msg
          )
        )
        setIsLoading(false)
        setAgentStatus(null)
        return
      }

      // SKF Copilot mode: local LangChain RAG, SSE streaming
      if (activeMode === 'skf') {
        const skfRes = await fetch('/api/skf/chat-stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: userMessage, session_id: USER_ID })
        })
        if (!skfRes.ok) throw new Error(`SKF Copilot Error: ${skfRes.status}`)

        const skfReader = skfRes.body.getReader()
        const skfDecoder = new TextDecoder()
        let skfContent = ''
        let skfBuffer = ''

        while (true) {
          const { done, value } = await skfReader.read()
          if (done) break
          skfBuffer += skfDecoder.decode(value, { stream: true })
          const lines = skfBuffer.split('\n')
          skfBuffer = lines.pop() || ''
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const event = JSON.parse(line.slice(6))
              if (event.event === 'tool') {
                setAgentStatus('searching')
              } else if (event.event === 'message') {
                setAgentStatus('writing')
                skfContent += event.answer || ''
                setMessages(prev =>
                  prev.map(msg =>
                    msg.id === aiMessageId ? { ...msg, content: skfContent } : msg
                  )
                )
              } else if (event.event === 'message_end') {
                setAgentStatus(null)
              } else if (event.event === 'error') {
                throw new Error(event.message || 'SKF Copilot error')
              }
            } catch (e) {
              if (e.message && e.message !== 'SKF Copilot error' && !e.message.startsWith('Unexpected')) throw e
            }
          }
        }
        setIsLoading(false)
        setAgentStatus(null)
        inputRef.current?.focus()
        return
      }

      const response = await fetch(`${BASE_URL}/chat-messages`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          inputs: {},
          query: userMessage,
          response_mode: 'streaming',
          user: USER_ID,
          ...(conversationId && { conversation_id: conversationId })
        })
      })

      if (!response.ok) {
        throw new Error(`API Error: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let fullContent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') continue

            try {
              const event = JSON.parse(data)

              if (event.event === 'agent_thought') {
                const tool = event.tool || ''
                if (tool) {
                  setAgentStatus('searching')
                } else {
                  setAgentStatus('thinking')
                }
              }

              if (event.event === 'message' || event.event === 'agent_message') {
                setAgentStatus('writing')
                fullContent += event.answer || ''
                setMessages(prev =>
                  prev.map(msg =>
                    msg.id === aiMessageId
                      ? { ...msg, content: fullContent }
                      : msg
                  )
                )
              }

              if (event.conversation_id && !conversationId) {
                setConversationId(event.conversation_id)
              }

              if (event.event === 'message_end') {
                setAgentStatus(null)
              }

              if (event.event === 'error') {
                throw new Error(event.message || 'Unknown error')
              }
            } catch (e) {
              if (e.message !== 'Unknown error') continue
              throw e
            }
          }
        }
      }
    } catch (error) {
      console.error('Error:', error)
      setMessages(prev =>
        prev.map(msg =>
          msg.id === aiMessageId
            ? { ...msg, content: `❌ Error: ${error.message}`, isError: true }
            : msg
        )
      )
    } finally {
      setIsLoading(false)
      setAgentStatus(null)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    sendMessage()
  }

  const startNewChat = () => {
    // Also reset the SKF Copilot server-side session so old context doesn't leak in
    fetch('/api/skf/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: '', session_id: USER_ID })
    }).catch(() => {})
    setMessages([
      { role: 'assistant', content: 'Hello! How can I help you with your issue today?', time: new Date() }
    ])
    setConversationId(null)
    setInput('')
    setAgentStatus(null)
    setShowHistoryModal(false)
    inputRef.current?.focus()
  }

  const formatTime = (date) => {
    if (!date) return ''
    return new Date(date).toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit',
      hour12: true 
    })
  }

  const formatDate = (timestamp) => {
    const date = new Date(timestamp * 1000)
    const now = new Date()
    const diff = now - date
    
    if (diff < 3600000) return `${Math.floor(diff / 60000)} min ago`
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} hours ago`
    if (diff < 604800000) return `${Math.floor(diff / 86400000)} days ago`
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  // Group conversations by time
  const groupConversations = () => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const yesterday = new Date(today - 86400000)
    const lastWeek = new Date(today - 604800000)

    const filtered = conversations.filter(c => 
      !historySearch || 
      (c.name || 'Untitled').toLowerCase().includes(historySearch.toLowerCase())
    )

    const groups = {
      today: [],
      yesterday: [],
      lastWeek: [],
      older: []
    }

    filtered.forEach(conv => {
      const convDate = new Date(conv.created_at * 1000)
      if (convDate >= today) groups.today.push(conv)
      else if (convDate >= yesterday) groups.yesterday.push(conv)
      else if (convDate >= lastWeek) groups.lastWeek.push(conv)
      else groups.older.push(conv)
    })

    return groups
  }

  const AgentStatusIndicator = () => {
    if (!agentStatus) return null

    const statusConfig = {
      thinking: { icon: '🤔', text: 'Thinking...', animation: 'pulse' },
      searching: { icon: '🔍', text: 'Searching knowledge base...', animation: 'search' },
      writing: { icon: '✍️', text: 'Writing response...', animation: 'write' }
    }

    const config = statusConfig[agentStatus]
    if (!config) return null

    return (
      <div className={`agent-status ${config.animation}`}>
        <span className="agent-status-icon">{config.icon}</span>
        <span className="agent-status-text">{config.text}</span>
        <div className="agent-status-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
    )
  }

  const groupedConversations = groupConversations()

  return (
    <div className={`app ${theme}`}>
      {/* History Modal */}
      {showHistoryModal && (
        <div className="history-modal-overlay">
          <div className="history-modal" ref={modalRef}>
            <div className="history-modal-header">
              <div className="history-search-wrapper">
                <svg viewBox="0 0 24 24" fill="currentColor" className="search-icon">
                  <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
                </svg>
                <input
                  type="text"
                  placeholder="Search..."
                  value={historySearch}
                  onChange={(e) => setHistorySearch(e.target.value)}
                  autoFocus
                />
              </div>
            </div>
            
            <div className="history-modal-content">
              <div className="history-section">
                <div className="history-section-title">Actions</div>
                <div 
                  className="history-action-item"
                  onClick={startNewChat}
                >
                  <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
                  </svg>
                  <span>Create New Chat</span>
                </div>
              </div>

              {loadingHistory ? (
                <div className="history-loading">Loading conversations...</div>
              ) : (
                <>
                  {groupedConversations.today.length > 0 && (
                    <div className="history-section">
                      <div className="history-section-title">Today</div>
                      {groupedConversations.today.map(conv => (
                        <ConversationItem 
                          key={conv.id} 
                          conv={conv} 
                          renamingConv={renamingConv}
                          setRenamingConv={setRenamingConv}
                          renameValue={renameValue}
                          setRenameValue={setRenameValue}
                          renameConversation={renameConversation}
                          deleteConversation={deleteConversation}
                          fetchMessages={fetchMessages}
                          formatDate={formatDate}
                          conversationId={conversationId}
                        />
                      ))}
                    </div>
                  )}

                  {groupedConversations.yesterday.length > 0 && (
                    <div className="history-section">
                      <div className="history-section-title">Yesterday</div>
                      {groupedConversations.yesterday.map(conv => (
                        <ConversationItem 
                          key={conv.id} 
                          conv={conv} 
                          renamingConv={renamingConv}
                          setRenamingConv={setRenamingConv}
                          renameValue={renameValue}
                          setRenameValue={setRenameValue}
                          renameConversation={renameConversation}
                          deleteConversation={deleteConversation}
                          fetchMessages={fetchMessages}
                          formatDate={formatDate}
                          conversationId={conversationId}
                        />
                      ))}
                    </div>
                  )}

                  {groupedConversations.lastWeek.length > 0 && (
                    <div className="history-section">
                      <div className="history-section-title">Last 7 Days</div>
                      {groupedConversations.lastWeek.map(conv => (
                        <ConversationItem 
                          key={conv.id} 
                          conv={conv} 
                          renamingConv={renamingConv}
                          setRenamingConv={setRenamingConv}
                          renameValue={renameValue}
                          setRenameValue={setRenameValue}
                          renameConversation={renameConversation}
                          deleteConversation={deleteConversation}
                          fetchMessages={fetchMessages}
                          formatDate={formatDate}
                          conversationId={conversationId}
                        />
                      ))}
                    </div>
                  )}

                  {groupedConversations.older.length > 0 && (
                    <div className="history-section">
                      <div className="history-section-title">Older</div>
                      {groupedConversations.older.map(conv => (
                        <ConversationItem 
                          key={conv.id} 
                          conv={conv} 
                          renamingConv={renamingConv}
                          setRenamingConv={setRenamingConv}
                          renameValue={renameValue}
                          setRenameValue={setRenameValue}
                          renameConversation={renameConversation}
                          deleteConversation={deleteConversation}
                          fetchMessages={fetchMessages}
                          formatDate={formatDate}
                          conversationId={conversationId}
                        />
                      ))}
                    </div>
                  )}

                  {conversations.length === 0 && (
                    <div className="history-empty">No conversation history</div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 左侧边栏 */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="logo">
            <div className="logo-icon">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/>
              </svg>
            </div>
            <span>HelpDesk</span>
          </div>
        </div>

        <div className="new-chat-wrapper">
          <button className="new-chat-btn" onClick={startNewChat}>
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
            </svg>
            <span>New Chat</span>
          </button>
        </div>

        <div style={{ display: 'flex', gap: '6px', padding: '0 16px 12px' }}>
          {[
            { id: 'dify', label: 'IT Helpdesk' },
            { id: 'skf', label: 'SKF Copilot' },
          ].map(m => (
            <button
              key={m.id}
              onClick={() => { setBotMode(m.id); startNewChat(); }}
              style={{
                flex: 1, padding: '6px 8px', fontSize: '12px', cursor: 'pointer',
                borderRadius: '8px',
                border: botMode === m.id ? '1px solid #58a6ff' : '1px solid rgba(128,128,128,0.35)',
                background: botMode === m.id ? 'rgba(88,166,255,0.18)' : 'transparent',
                color: botMode === m.id ? '#58a6ff' : 'inherit', fontWeight: 600,
              }}
            >
              {m.label}
            </button>
          ))}
        </div>

        <nav className="sidebar-nav">
          <a href="#" className="nav-item active">
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
            </svg>
            <div className="nav-text">
              <span className="nav-title">Current Chat</span>
              <span className="nav-subtitle">{conversationId ? 'Active Session' : 'New Session'}</span>
            </div>
          </a>
          <a 
            href="#" 
            className="nav-item"
            onClick={(e) => { e.preventDefault(); setShowHistoryModal(true); }}
          >
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9z"/>
            </svg>
            <div className="nav-text">
              <span className="nav-title">History</span>
              <span className="nav-subtitle">{conversations.length} conversations</span>
            </div>
          </a>
        </nav>

        <div className="sidebar-footer">
          <button className="theme-toggle" onClick={toggleTheme}>
            {theme === 'dark' ? (
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1z"/>
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9 9-4.03 9-9c0-.46-.04-.92-.1-1.36-.98 1.37-2.58 2.26-4.4 2.26-2.98 0-5.4-2.42-5.4-5.4 0-1.81.89-3.42 2.26-4.4-.44-.06-.9-.1-1.36-.1z"/>
              </svg>
            )}
            <span>{theme === 'dark' ? 'Light Mode' : 'Dark Mode'}</span>
          </button>

          {user ? (
            <div className="user-info">
              <div className="user-avatar">
                <img src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${user.email}`} alt="avatar" />
              </div>
              <div className="user-details">
                <span className="user-name">
                  {user.given_name || user.name?.split(' ')[0] || user.email?.split('@')[0] || 'User'}
                </span>
                <span className="user-role">Authenticated</span>
              </div>
              <button className="logout-btn" onClick={handleLogout} title="Sign out">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/>
                </svg>
              </button>
            </div>
          ) : (
            <button className="login-btn" onClick={handleLogin}>
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M11 7L9.6 8.4l2.6 2.6H2v2h10.2l-2.6 2.6L11 17l5-5-5-5zm9 12h-8v2h8c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2h-8v2h8v14z"/>
              </svg>
              <span>Sign in with SSO</span>
            </button>
          )}
        </div>
      </aside>

      {/* 主聊天区域 */}
      <main className="chat-main">
        <header className="chat-header">
          <div className="bot-info">
            <div className="bot-avatar">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
              </svg>
            </div>
            <div className="bot-details">
              <span className="bot-name">{botMode === 'skf' ? 'SKF Distributor Copilot' : 'Support Bot'}</span>
              <span className="bot-status">
                <span className="status-dot"></span>
                {agentStatus ? (
                  agentStatus === 'thinking' ? 'Thinking...' :
                  agentStatus === 'searching' ? 'Searching...' :
                  agentStatus === 'writing' ? 'Typing...' : 'Online'
                ) : 'Online'}
              </span>
            </div>
          </div>
          <div className="header-actions">
            <button className="icon-btn" onClick={toggleTheme} title="Toggle theme">
              {theme === 'dark' ? (
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5z"/>
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9 9-4.03 9-9c0-.46-.04-.92-.1-1.36-.98 1.37-2.58 2.26-4.4 2.26-2.98 0-5.4-2.42-5.4-5.4 0-1.81.89-3.42 2.26-4.4-.44-.06-.9-.1-1.36-.1z"/>
                </svg>
              )}
            </button>
            <button className="icon-btn" onClick={() => setShowHistoryModal(true)} title="History">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9z"/>
              </svg>
            </button>
            <button className="icon-btn">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>
              </svg>
            </button>
          </div>
        </header>

        <div className="messages-container">
          <div className="date-divider">
            <span>Today, {new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
          </div>

          <div className="messages">
            {messages.map((msg, idx) => (
              <div key={msg.id || idx} className={`message ${msg.role} ${msg.isError ? 'error' : ''}`}>
                {msg.role === 'assistant' && (
                  <div className="message-avatar">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
                    </svg>
                  </div>
                )}
                <div className="message-wrapper">
                  {msg.role === 'assistant' && (
                    <span className="message-sender">Support Bot <span className="message-time">{formatTime(msg.time)}</span></span>
                  )}
                  {msg.role === 'user' && (
                    <span className="message-sender user-sender">{formatTime(msg.time)} <span className="you-label">You</span></span>
                  )}
                  <div className="message-bubble">
                    {msg.role === 'assistant' && msg.content ? (
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        rehypePlugins={[rehypeRaw]}
                        components={{
                          a: ({ node, ...props }) => (
                            <a {...props} target="_blank" rel="noopener noreferrer" />
                          ),
                          img: ({ node, ...props }) => (
                            <img
                              {...props}
                              onError={(e) => { e.target.style.display = 'none' }}
                              onLoad={(e) => { e.target.style.display = '' }}
                            />
                          )
                        }}
                      >{msg.content}</ReactMarkdown>
                    ) : msg.role === 'assistant' && !msg.content ? (
                      <AgentStatusIndicator />
                    ) : (
                      msg.content
                    )}
                  </div>
                </div>
                {msg.role === 'user' && (
                  <div className="message-avatar user-avatar">
                    <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=John" alt="avatar" />
                  </div>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>

        <div className="quick-actions">
          {quickActions.map((action, idx) => (
            <button 
              key={idx} 
              className="quick-btn"
              onClick={() => sendMessage(action)}
              disabled={isLoading}
            >
              {action}
            </button>
          ))}
        </div>

        <footer className="chat-footer">
          <form className="input-wrapper" onSubmit={handleSubmit}>
            <button type="button" className="attach-btn">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5 11h-4v4h-2v-4H7v-2h4V7h2v4h4v2z"/>
              </svg>
            </button>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type your message..."
              disabled={isLoading}
              autoComplete="off"
            />
            <button type="button" className="emoji-btn">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm3.5-9c.83 0 1.5-.67 1.5-1.5S16.33 8 15.5 8 14 8.67 14 9.5s.67 1.5 1.5 1.5zm-7 0c.83 0 1.5-.67 1.5-1.5S9.33 8 8.5 8 7 8.67 7 9.5 7.67 11 8.5 11zm3.5 6.5c2.33 0 4.31-1.46 5.11-3.5H6.89c.8 2.04 2.78 3.5 5.11 3.5z"/>
              </svg>
            </button>
            <button
              type="submit"
              className="send-btn"
              disabled={!input.trim() || isLoading}
            >
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
          </form>
          <p className="input-hint">Press Enter to send, Shift + Enter for new line</p>
        </footer>
      </main>
    </div>
  )
}

// Conversation Item Component - using CSS hover instead of JS state for reliability
function ConversationItem({ 
  conv, renamingConv, setRenamingConv,
  renameValue, setRenameValue, renameConversation, deleteConversation,
  fetchMessages, formatDate, conversationId 
}) {
  const isRenaming = renamingConv === conv.id

  const handleDelete = (e) => {
    e.stopPropagation()
    e.preventDefault()
    deleteConversation(conv.id, e)
  }

  const handleRename = (e) => {
    e.stopPropagation()
    e.preventDefault()
    setRenamingConv(conv.id)
    setRenameValue(conv.name || '')
  }

  return (
    <div 
      className={`history-conv-item ${conv.id === conversationId ? 'active' : ''}`}
      onClick={() => !isRenaming && fetchMessages(conv.id)}
    >
      <div className="history-conv-content">
        {isRenaming ? (
          <input
            type="text"
            className="rename-input"
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') renameConversation(conv.id)
              if (e.key === 'Escape') setRenamingConv(null)
            }}
            onBlur={() => renameConversation(conv.id)}
            onClick={(e) => e.stopPropagation()}
            autoFocus
          />
        ) : (
          <>
            <span className="history-conv-name">{conv.name || 'Untitled Chat'}</span>
            <span className="history-conv-time">{formatDate(conv.created_at)}</span>
          </>
        )}
      </div>
      
      {!isRenaming && (
        <div className="history-conv-actions">
          <button 
            className="conv-action-btn" 
            title="Rename"
            onClick={handleRename}
          >
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
            </svg>
          </button>
          <button 
            className="conv-action-btn delete" 
            title="Delete"
            onClick={handleDelete}
          >
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
            </svg>
          </button>
        </div>
      )}
    </div>
  )
}

export default App
