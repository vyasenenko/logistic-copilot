const messagesEl = document.getElementById('messages');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const clearBtn = document.getElementById('clearBtn');
const pageBtn = document.getElementById('pageBtn');
const apiBaseInput = document.getElementById('apiBaseInput');
const saveApiBtn = document.getElementById('saveApiBtn');
const themeBtn = document.getElementById('themeBtn');

const STORAGE_MESSAGES = 'assistant_messages';
const STORAGE_API_BASE = 'api_base_url';
const STORAGE_CONVERSATION = 'conversation_id';
const STORAGE_THEME = 'ui_theme';
const DEFAULT_API_BASE = 'http://localhost:8000';

(function configureMarked() {
  if (typeof marked === 'undefined') return;
  try {
    marked.use({ gfm: true, breaks: true });
  } catch (e) {
    console.warn('marked.use failed', e);
  }
})();

/**
 * @param {string} raw
 * @returns {string | null} raw HTML from marked, or null if unavailable / async
 */
function parseMarkdownToUnsafeHtml(raw) {
  if (typeof marked === 'undefined') return null;
  try {
    if (typeof marked.parse === 'function') {
      const html = marked.parse(raw);
      if (html != null && typeof /** @type {any} */ (html).then === 'function') return null;
      return typeof html === 'string' ? html : html != null ? String(html) : null;
    }
    const fn = /** @type {any} */ (marked);
    if (typeof fn === 'function') {
      const html = fn(raw);
      return typeof html === 'string' ? html : null;
    }
  } catch (e) {
    console.warn('marked failed', e);
  }
  return null;
}

const THEME_ICON_SUN =
  '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>';
const THEME_ICON_MOON =
  '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';

function updateThemeButton(theme) {
  if (!themeBtn) return;
  const isLight = theme === 'light';
  themeBtn.innerHTML = isLight ? THEME_ICON_MOON : THEME_ICON_SUN;
  themeBtn.title = isLight ? 'Switch to dark theme' : 'Switch to light theme';
  themeBtn.setAttribute('aria-label', themeBtn.title);
}

/** @param {'dark' | 'light'} theme */
function applyTheme(theme, persist) {
  const t = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
  updateThemeButton(t);
  if (persist) chrome.storage.local.set({ [STORAGE_THEME]: t });
}

function initTheme() {
  chrome.storage.local.get([STORAGE_THEME], (r) => {
    const t = r[STORAGE_THEME] === 'light' ? 'light' : 'dark';
    applyTheme(t, false);
  });
  themeBtn?.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    applyTheme(cur === 'light' ? 'dark' : 'light', true);
  });
}

initTheme();

function getTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function loadApiBase(callback) {
  chrome.storage.local.get([STORAGE_API_BASE], (r) => {
    callback((r[STORAGE_API_BASE] || DEFAULT_API_BASE).replace(/\/$/, ''));
  });
}

function saveApiBase(url, callback) {
  const trimmed = (url || '').trim().replace(/\/$/, '') || DEFAULT_API_BASE;
  chrome.storage.local.set({ [STORAGE_API_BASE]: trimmed }, () => callback(trimmed));
}

function loadConversationId(callback) {
  chrome.storage.local.get([STORAGE_CONVERSATION], (r) => {
    callback(r[STORAGE_CONVERSATION] || null);
  });
}

function saveConversationId(id) {
  if (id) chrome.storage.local.set({ [STORAGE_CONVERSATION]: id });
}

function saveMessages(msgs) {
  chrome.storage.local.set({ [STORAGE_MESSAGES]: msgs });
}

function loadMessages(callback) {
  chrome.storage.local.get([STORAGE_MESSAGES], (result) => {
    callback(result[STORAGE_MESSAGES] || []);
  });
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function stringifySafe(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

function truncate(s, n) {
  if (!s || s.length <= n) return s;
  return `${s.slice(0, n)}…`;
}

function renderMarkdown(text) {
  const raw = text == null ? '' : String(text);
  if (!raw.trim()) return '<p class="text-muted">…</p>';
  const unsafe = parseMarkdownToUnsafeHtml(raw);
  if (unsafe != null && typeof DOMPurify !== 'undefined') {
    try {
      return DOMPurify.sanitize(unsafe, { USE_PROFILES: { html: true } });
    } catch (e) {
      console.warn('DOMPurify.sanitize failed', e);
      try {
        return DOMPurify.sanitize(unsafe);
      } catch (e2) {
        console.warn('DOMPurify fallback failed', e2);
      }
    }
  }
  if (unsafe != null && typeof DOMPurify === 'undefined') {
    return unsafe;
  }
  console.warn('Markdown parser unavailable; plain text fallback');
  return `<p>${escapeHtml(raw).replace(/\n/g, '<br>')}</p>`;
}

/** @param {{ tool: string, status: string, toolInput?: object, toolOutput?: string }} tool */
function buildInlineToolAside(tool) {
  const aside = document.createElement('aside');
  aside.className = 'inline-tool' + (tool.status === 'running' ? ' inline-tool--running' : '');
  aside._tool = tool;

  const bar = document.createElement('div');
  bar.className = 'inline-tool__bar';
  const glyph = document.createElement('span');
  glyph.className = 'inline-tool__glyph';
  glyph.textContent = '⟡';
  glyph.setAttribute('aria-hidden', 'true');
  const name = document.createElement('span');
  name.className = 'inline-tool__name';
  name.textContent = tool.tool;
  const pill = document.createElement('span');
  pill.className =
    'inline-tool__pill ' + (tool.status === 'running' ? 'inline-tool__pill--run' : 'inline-tool__pill--done');
  pill.textContent = tool.status === 'running' ? 'Running' : 'Done';
  bar.appendChild(glyph);
  bar.appendChild(name);
  bar.appendChild(pill);

  const details = document.createElement('details');
  details.className = 'inline-tool__drawer';
  const sum = document.createElement('summary');
  sum.textContent = 'Arguments & output';
  const panels = document.createElement('div');
  panels.className = 'inline-tool__panels';
  details.appendChild(sum);
  details.appendChild(panels);

  aside.appendChild(bar);
  aside.appendChild(details);
  aside._pill = pill;
  aside._panels = panels;
  refreshInlineToolPanels(aside);
  return aside;
}

function refreshInlineToolPanels(aside) {
  const t = aside._tool;
  if (!aside._pill || !aside._panels) return;
  aside.classList.toggle('inline-tool--running', t.status === 'running');
  aside._pill.textContent = t.status === 'running' ? 'Running' : 'Done';
  aside._pill.className =
    'inline-tool__pill ' + (t.status === 'running' ? 'inline-tool__pill--run' : 'inline-tool__pill--done');

  aside._panels.innerHTML = '';
  if (t.toolInput && Object.keys(t.toolInput).length) {
    const lab = document.createElement('div');
    lab.className = 'inline-tool__mono-label';
    lab.textContent = 'Arguments';
    const pre = document.createElement('pre');
    pre.className = 'inline-tool__mono';
    pre.textContent = stringifySafe(t.toolInput);
    aside._panels.appendChild(lab);
    aside._panels.appendChild(pre);
  }
  if (t.toolOutput && t.status === 'done') {
    const lab = document.createElement('div');
    lab.className = 'inline-tool__mono-label';
    lab.textContent = 'Output';
    const pre = document.createElement('pre');
    pre.className = 'inline-tool__mono';
    pre.textContent = truncate(t.toolOutput, 3000);
    aside._panels.appendChild(lab);
    aside._panels.appendChild(pre);
  }
}

function appendUserTurn(text, time) {
  const article = document.createElement('article');
  article.className = 'turn turn--user';
  const line = document.createElement('div');
  line.className = 'user-line';
  line.textContent = text;
  const meta = document.createElement('time');
  meta.className = 'turn-meta';
  meta.textContent = time || getTime();
  article.appendChild(line);
  article.appendChild(meta);
  messagesEl.appendChild(article);
  scrollToBottom();
  return article;
}

/** @param {Array<{ type: string, text?: string, tool?: object }>} segments */
function renderAssistantFromSegments(segments, time) {
  const article = document.createElement('article');
  article.className = 'turn turn--assistant';
  const flow = document.createElement('div');
  flow.className = 'assistant-flow';
  for (const s of segments) {
    if (s.type === 'text' && s.text != null) {
      const d = document.createElement('div');
      d.className = 'markdown-body';
      d.innerHTML = renderMarkdown(s.text);
      flow.appendChild(d);
    } else if (s.type === 'tool' && s.tool) {
      const copy = {
        tool: s.tool.tool,
        status: s.tool.status || 'done',
        toolInput: s.tool.toolInput,
        toolOutput: s.tool.toolOutput,
      };
      flow.appendChild(buildInlineToolAside(copy));
    }
  }
  const meta = document.createElement('time');
  meta.className = 'turn-meta';
  meta.textContent = time || getTime();
  article.appendChild(flow);
  article.appendChild(meta);
  messagesEl.appendChild(article);
  scrollToBottom();
  return article;
}

function appendAssistantTurn(text, time, tools) {
  /** @type {Array<{ type: string, text?: string, tool?: object }>} */
  const segments = [{ type: 'text', text: text || '' }];
  if (tools && tools.length) {
    tools.forEach((t) => {
      segments.push({
        type: 'tool',
        tool: {
          tool: t.tool,
          status: t.status || 'done',
          toolInput: t.toolInput,
          toolOutput: t.toolOutput,
        },
      });
    });
  }
  renderAssistantFromSegments(segments, time);
}

function showTyping() {
  const article = document.createElement('article');
  article.className = 'turn turn--assistant turn--typing';
  const flow = document.createElement('div');
  flow.className = 'assistant-flow';
  const dots = document.createElement('div');
  dots.className = 'typing-dots';
  dots.innerHTML = '<span></span><span></span><span></span>';
  flow.appendChild(dots);
  article.appendChild(flow);
  messagesEl.appendChild(article);
  scrollToBottom();
  return article;
}

async function streamChat(apiBase, conversationId, userText, onToken, onEvent) {
  const url = `${apiBase}/api/chat`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      content: userText,
      conversation_id: conversationId || undefined,
    }),
  });

  const hdrConv = res.headers.get('X-Conversation-Id');
  if (hdrConv) onEvent({ event: '_conversation_id', data: hdrConv });

  if (!res.ok) {
    const t = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${t || res.statusText}`);
  }

  const reader = res.body?.getReader();
  const decoder = new TextDecoder();
  if (!reader) throw new Error('No response body');

  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      let parsed;
      try {
        parsed = JSON.parse(line.slice(6));
      } catch {
        continue;
      }
      onEvent(parsed);
      if (parsed.event === 'token' && typeof parsed.data === 'string') {
        onToken(parsed.data);
      }
    }
  }
  if (buffer.startsWith('data: ')) {
    try {
      const parsed = JSON.parse(buffer.slice(6));
      onEvent(parsed);
      if (parsed.event === 'token' && typeof parsed.data === 'string') onToken(parsed.data);
    } catch {
      /* ignore */
    }
  }
}

function sealTextTail(streamBody) {
  const tail = streamBody.querySelector('.stream-plain--tail');
  if (tail) {
    tail.classList.remove('stream-plain--tail');
  }
}

function getOrCreateTextTail(streamBody) {
  let tail = streamBody.querySelector('.stream-plain--tail');
  if (!tail) {
    tail = document.createElement('div');
    tail.className = 'markdown-body stream-plain stream-plain--tail';
    streamBody.appendChild(tail);
  }
  return tail;
}

function finalizeStreamMarkdown(streamBody) {
  for (const el of [...streamBody.children]) {
    if (el.classList.contains('stream-plain')) {
      const raw = el.textContent || '';
      el.className = 'markdown-body';
      if (raw.trim()) {
        el.innerHTML = renderMarkdown(raw);
      } else {
        el.remove();
      }
    }
    if (el.classList.contains('inline-tool')) {
      const det = el.querySelector('details.inline-tool__drawer');
      if (det) det.open = false;
    }
  }
}

let history = [];
let conversationId = null;

async function sendMessage() {
  const text = userInput.value.trim();
  if (!text) return;

  userInput.value = '';
  autoResize();
  setSending(true);

  const userTime = getTime();
  appendUserTurn(text, userTime);
  history.push({ role: 'user', text, time: userTime });

  const typingArticle = showTyping();

  let apiBase = DEFAULT_API_BASE;
  await new Promise((r) => {
    loadApiBase((b) => {
      apiBase = b;
      r();
    });
  });
  await new Promise((r) => {
    loadConversationId((cid) => {
      conversationId = cid;
      r();
    });
  });

  let pendingText = '';
  /** @type {{ tool: string, status: string, toolInput?: object, toolOutput?: string }[]} */
  const toolsLog = [];
  /** @type {HTMLElement[]} */
  const toolAsides = [];

  /** @type {HTMLElement | null} */
  let streamArticle = null;
  /** @type {HTMLElement | null} */
  let streamBody = null;

  function ensureStreamTurn() {
    if (streamArticle) return;
    typingArticle.remove();
    streamArticle = document.createElement('article');
    streamArticle.className = 'turn turn--assistant streaming';
    streamBody = document.createElement('div');
    streamBody.className = 'assistant-flow';
    const meta = document.createElement('time');
    meta.className = 'turn-meta';
    meta.textContent = getTime();
    streamArticle.appendChild(streamBody);
    streamArticle.appendChild(meta);
    messagesEl.appendChild(streamArticle);
    scrollToBottom();
  }

  try {
    await streamChat(
      apiBase,
      conversationId,
      text,
      (chunk) => {
        pendingText += chunk;
        ensureStreamTurn();
        if (streamBody) getOrCreateTextTail(streamBody).textContent = pendingText;
        scrollToBottom();
      },
      (ev) => {
        if (ev.event === '_conversation_id' && typeof ev.data === 'string') {
          conversationId = ev.data;
          saveConversationId(conversationId);
          return;
        }
        if (ev.event === 'conversation_id' && typeof ev.data === 'string') {
          conversationId = ev.data;
          saveConversationId(conversationId);
        }
        if (ev.event === 'tool_start') {
          ensureStreamTurn();
          if (streamBody && pendingText) {
            const tail = streamBody.querySelector('.stream-plain--tail');
            if (tail) {
              tail.classList.remove('stream-plain--tail');
            } else {
              const block = document.createElement('div');
              block.className = 'markdown-body stream-plain';
              block.textContent = pendingText;
              streamBody.appendChild(block);
            }
            pendingText = '';
          }
          const raw = ev.data;
          const toolName =
            typeof raw === 'string' ? raw : String(raw?.tool_name || raw?.name || 'tool');
          const toolInput =
            typeof raw === 'object' && raw !== null && raw.tool_input ? raw.tool_input : undefined;
          const toolState = { tool: toolName, status: 'running', toolInput };
          toolsLog.push(toolState);
          if (streamBody) {
            const aside = buildInlineToolAside(toolState);
            streamBody.appendChild(aside);
            toolAsides.push(aside);
          }
          scrollToBottom();
        }
        if (ev.event === 'tool_end') {
          const raw = ev.data;
          const toolName =
            typeof raw === 'object' && raw !== null && raw.tool_name ? String(raw.tool_name) : null;
          const toolOutput =
            typeof raw === 'object' && raw !== null && raw.tool_output
              ? String(raw.tool_output)
              : typeof raw === 'string'
                ? raw
                : '';
          let idx = -1;
          if (toolName) {
            for (let i = toolsLog.length - 1; i >= 0; i--) {
              if (toolsLog[i].status === 'running' && toolsLog[i].tool === toolName) {
                idx = i;
                break;
              }
            }
          }
          if (idx < 0) {
            for (let i = toolsLog.length - 1; i >= 0; i--) {
              if (toolsLog[i].status === 'running') {
                idx = i;
                break;
              }
            }
          }
          if (idx >= 0) {
            toolsLog[idx] = {
              ...toolsLog[idx],
              status: 'done',
              toolOutput: toolOutput || toolsLog[idx].toolOutput,
            };
            const aside = toolAsides[idx];
            if (aside) refreshInlineToolPanels(aside);
          }
          scrollToBottom();
        }
        if (ev.event === 'error') {
          pendingText += `\n\n**Error**\n\n${typeof ev.data === 'string' ? ev.data : stringifySafe(ev.data)}`;
          if (streamBody) getOrCreateTextTail(streamBody).textContent = pendingText;
        }
        if (typeof ev.conversation_id === 'string') {
          conversationId = ev.conversation_id;
          saveConversationId(conversationId);
        }
      }
    );

    typingArticle.remove();
    const finalTime = getTime();

    if (streamArticle && streamBody) {
      if (pendingText.trim()) {
        const tail = streamBody.querySelector('.stream-plain--tail');
        if (tail) {
          tail.textContent = pendingText;
          tail.classList.remove('stream-plain--tail');
        } else {
          const block = document.createElement('div');
          block.className = 'markdown-body stream-plain';
          block.textContent = pendingText;
          streamBody.appendChild(block);
        }
        pendingText = '';
      } else {
        sealTextTail(streamBody);
      }

      /** @type {Array<{ type: string, text?: string, tool?: object }>} */
      const segments = [];
      for (const el of streamBody.children) {
        if (el.classList.contains('stream-plain')) {
          const t = el.textContent || '';
          if (t.trim()) segments.push({ type: 'text', text: t });
        }
        if (el.classList.contains('inline-tool')) {
          const ref = el._tool;
          if (ref) {
            segments.push({
              type: 'tool',
              tool: {
                tool: ref.tool,
                status: ref.status,
                toolInput: ref.toolInput ? { ...ref.toolInput } : undefined,
                toolOutput: ref.toolOutput,
              },
            });
          }
        }
      }

      finalizeStreamMarkdown(streamBody);
      streamArticle.classList.remove('streaming');
      const meta = streamArticle.querySelector('.turn-meta');
      if (meta) meta.textContent = finalTime;

      const flatText = segments
        .filter((s) => s.type === 'text')
        .map((s) => s.text)
        .join('\n\n');

      history.push({
        role: 'assistant',
        time: finalTime,
        segments: segments.length ? segments : [{ type: 'text', text: flatText || '…' }],
        text: flatText || '…',
      });
    } else {
      appendAssistantTurn('…', finalTime, null);
      history.push({ role: 'assistant', time: finalTime, segments: [{ type: 'text', text: '…' }], text: '…' });
    }
    saveMessages(history);
  } catch (err) {
    typingArticle.remove();
    const msg = err instanceof Error ? err.message : String(err);
    appendAssistantTurn(`**Request failed**\n\n\`\`\`\n${escapeHtml(msg)}\n\`\`\``, getTime(), null);
    history.push({
      role: 'assistant',
      time: getTime(),
      segments: [{ type: 'text', text: `Request failed: ${msg}` }],
      text: `Request failed: ${msg}`,
    });
    saveMessages(history);
  }

  setSending(false);
}

function setSending(isSending) {
  sendBtn.disabled = isSending;
  userInput.disabled = isSending;
}

pageBtn.addEventListener('click', async () => {
  pageBtn.disabled = true;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      appendAssistantTurn('Could not access the **active tab**.', getTime(), null);
      return;
    }
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({
        title: document.title,
        url: location.href,
        text: document.body.innerText.replace(/\s+/g, ' ').trim().slice(0, 500),
      }),
    });
    const { title, url, text } = results[0].result;
    const md = `### Active tab\n\n**${title}**\n\n${url}\n\n\`\`\`\n${text}\n\`\`\``;
    appendAssistantTurn(md, getTime(), null);
  } catch (err) {
    appendAssistantTurn(`**Error**\n\n${escapeHtml(err.message)}`, getTime(), null);
  } finally {
    pageBtn.disabled = false;
  }
});

clearBtn.addEventListener('click', () => {
  if (!confirm('Clear conversation history?')) return;
  history = [];
  conversationId = null;
  chrome.storage.local.remove([STORAGE_MESSAGES, STORAGE_CONVERSATION]);
  messagesEl.innerHTML = '';
  const t = getTime();
  appendAssistantTurn('Chat cleared. **Conversation** reset.', t, null);
  history.push({
    role: 'assistant',
    time: t,
    segments: [{ type: 'text', text: 'Chat cleared. Conversation reset.' }],
    text: 'Chat cleared. Conversation reset.',
  });
  saveMessages(history);
});

function autoResize() {
  userInput.style.height = 'auto';
  userInput.style.height = `${Math.min(userInput.scrollHeight, 140)}px`;
}

userInput.addEventListener('input', autoResize);

userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener('click', sendMessage);

saveApiBtn.addEventListener('click', () => {
  saveApiBase(apiBaseInput.value, (saved) => {
    apiBaseInput.value = saved;
    saveApiBtn.textContent = 'Saved';
    setTimeout(() => {
      saveApiBtn.textContent = 'Save';
    }, 1200);
  });
});

loadApiBase((base) => {
  apiBaseInput.value = base;
});

loadMessages((saved) => {
  if (saved.length === 0) return;
  messagesEl.innerHTML = '';
  history = saved;
  saved.forEach((msg) => {
    if (msg.role === 'user') appendUserTurn(msg.text, msg.time);
    else if (msg.segments && Array.isArray(msg.segments)) renderAssistantFromSegments(msg.segments, msg.time);
    else appendAssistantTurn(msg.text, msg.time, msg.tools);
  });
});

loadConversationId((cid) => {
  conversationId = cid;
});
