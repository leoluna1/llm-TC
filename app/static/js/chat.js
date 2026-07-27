// ── Globals ───────────────────────────────────────────────────────────────────
let isResponseInProgress = false;

const COPY_ICON  = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
const CHECK_ICON = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const chatMessages    = document.getElementById('chatMessages');
const chatPlaceholder = document.getElementById('chatPlaceholder');
const questionForm    = document.getElementById('questionForm');
const questionInput   = document.getElementById('questionInput');
const sendBtn         = document.getElementById('sendBtn');
const quickQuestions  = document.getElementById('quickQuestions');

// ── Quick questions ───────────────────────────────────────────────────────────
const QUICK_QS = [
    '¿Cuáles son mis derechos?',
    '¿Puedo cancelar el servicio?',
    '¿Qué datos recopilan?',
    '¿Hay cláusulas problemáticas?',
];

function buildQuickQuestions() {
    quickQuestions.innerHTML = '';
    QUICK_QS.forEach(q => {
        const btn = document.createElement('button');
        btn.className = 'quick-btn';
        btn.textContent = q;
        btn.type = 'button';
        btn.addEventListener('click', () => {
            if (isResponseInProgress) return;
            questionInput.value = q;
            questionForm.dispatchEvent(new Event('submit'));
        });
        quickQuestions.appendChild(btn);
    });
}

// ── Init chat ─────────────────────────────────────────────────────────────────
function initChat(sessionId) {
    if (!sessionId) return;

    clearChatMessages();
    chatPlaceholder.style.display = 'none';

    addMessageToChat(
        'assistant',
        '¡Hola! Cargué tu documento y lo estoy analizando. Podés hacerme preguntas mientras tanto.',
        new Date().toISOString()
    );

    buildQuickQuestions();
    quickQuestions.style.display = 'flex';
    sendBtn.disabled = false;
    questionInput.disabled = false;

    questionForm.onsubmit = e => {
        e.preventDefault();
        const text = questionInput.value.trim();
        if (!isResponseInProgress && text) sendQuestion(sessionId, text);
    };

    questionInput.addEventListener('input', resizeInput);
    questionInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            questionForm.dispatchEvent(new Event('submit'));
        }
    });

    scrollToBottom();
    updateChatMessages();
}

function resizeInput() {
    questionInput.style.height = 'auto';
    questionInput.style.height = Math.min(questionInput.scrollHeight, 100) + 'px';
}

// ── Load messages from server ─────────────────────────────────────────────────
async function updateChatMessages() {
    if (!currentSessionId) return;
    try {
        const res  = await fetch(`/api/chat/${currentSessionId}`);
        const data = await res.json();
        if (data.success && data.messages?.length) {
            clearChatMessages();
            data.messages.forEach(m => addMessageToChat(m.role, m.content, m.timestamp));
            scrollToBottom();
        }
    } catch (err) {
        console.error('Error al cargar mensajes:', err);
    }
}

// ── Send question — STREAMING SSE ─────────────────────────────────────────────
async function sendQuestion(sessionId, question) {
    isResponseInProgress = true;
    sendBtn.disabled = true;

    addMessageToChat('user', question, new Date().toISOString());
    questionInput.value = '';
    questionInput.style.height = 'auto';

    // Create streaming bubble
    const { msgEl, bubble } = createStreamingBubble();
    let accumulated = '';

    try {
        const url = `/api/stream_question?session_id=${encodeURIComponent(sessionId)}&question=${encodeURIComponent(question)}`;
        const response = await fetch(url);

        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

        const reader  = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer    = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete line

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const raw = line.slice(6).trim();
                if (raw === '[DONE]') break;
                try {
                    const parsed = JSON.parse(raw);
                    if (parsed.token) {
                        accumulated += parsed.token;
                        // Remove cursor, render markdown, add cursor back
                        bubble.innerHTML = marked.parse(accumulated) + '<span class="stream-cursor"></span>';
                        scrollToBottom();
                    }
                } catch { /* partial JSON, skip */ }
            }
        }

        // Finalize — remove cursor, set time, add copy button
        bubble.innerHTML = marked.parse(accumulated || 'Sin respuesta.');
        const timeEl = msgEl.querySelector('.msg-time');
        if (timeEl) timeEl.textContent = formatTime(new Date().toISOString());
        const footerEl = msgEl.querySelector('.msg-footer');
        if (footerEl && !msgEl.querySelector('.msg-copy-btn')) {
            const copyBtn = document.createElement('button');
            copyBtn.className = 'msg-copy-btn';
            copyBtn.type = 'button';
            copyBtn.title = 'Copiar respuesta';
            copyBtn.setAttribute('aria-label', 'Copiar respuesta');
            copyBtn.innerHTML = COPY_ICON;
            footerEl.appendChild(copyBtn);
            attachCopyHandler(msgEl);
        }

    } catch (err) {
        console.error('Error en streaming:', err);
        bubble.innerHTML = 'Hubo un problema de conexión. Intentá de nuevo en un momento.';
    } finally {
        isResponseInProgress = false;
        sendBtn.disabled = false;
        scrollToBottom();
    }
}

// ── Streaming bubble ──────────────────────────────────────────────────────────
function createStreamingBubble() {
    chatPlaceholder.style.display = 'none';
    const aiAvatar = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/><circle cx="12" cy="16" r="1" fill="currentColor"/></svg>`;
    const msgEl = document.createElement('div');
    msgEl.className = 'message msg-assistant';
    msgEl.innerHTML = `
        <div class="msg-avatar" aria-hidden="true">${aiAvatar}</div>
        <div class="msg-body">
            <div class="msg-bubble"><span class="stream-cursor"></span></div>
            <div class="msg-footer">
                <div class="msg-time"></div>
            </div>
        </div>`;
    chatMessages.appendChild(msgEl);
    scrollToBottom();
    const bubble = msgEl.querySelector('.msg-bubble');
    return { msgEl, bubble };
}

// ── Message rendering ─────────────────────────────────────────────────────────
function clearChatMessages() {
    Array.from(chatMessages.children).forEach(child => {
        if (child.id !== 'chatPlaceholder') child.remove();
    });
}

function addMessageToChat(role, content, timestamp) {
    chatPlaceholder.style.display = 'none';
    const msg = document.createElement('div');
    msg.className = `message msg-${role}`;

    const bubbleHtml = role === 'assistant' ? marked.parse(content) : escapeHtml(content);
    const userAvatar = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`;
    const aiAvatar   = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/><circle cx="12" cy="16" r="1" fill="currentColor"/></svg>`;

    msg.innerHTML = `
        <div class="msg-avatar" aria-hidden="true">${role === 'user' ? userAvatar : aiAvatar}</div>
        <div class="msg-body">
            <div class="msg-bubble">${bubbleHtml}</div>
            <div class="msg-footer">
                <div class="msg-time">${formatTime(timestamp)}</div>
                ${role === 'assistant' ? `<button class="msg-copy-btn" type="button" title="Copiar respuesta" aria-label="Copiar respuesta">${COPY_ICON}</button>` : ''}
            </div>
        </div>`;

    if (role === 'assistant') {
        attachCopyHandler(msg);
    }

    chatMessages.appendChild(msg);
    scrollToBottom();
}

function attachCopyHandler(msgEl) {
    const btn = msgEl.querySelector('.msg-copy-btn');
    if (!btn) return;
    btn.addEventListener('click', function () {
        const text = msgEl.querySelector('.msg-bubble')?.innerText || '';
        navigator.clipboard.writeText(text).then(() => {
            btn.classList.add('copied');
            btn.innerHTML = CHECK_ICON;
            setTimeout(() => {
                btn.classList.remove('copied');
                btn.innerHTML = COPY_ICON;
            }, 1800);
        });
    });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function scrollToBottom() { chatMessages.scrollTop = chatMessages.scrollHeight; }

function formatTime(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
    catch { return ''; }
}

// escapeHtml is defined in main.js (loaded after this file)
