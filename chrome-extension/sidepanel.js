const messagesEl = document.getElementById('messages');
const userInput = document.getElementById('userInput');
const composerPlaceholderGhost = document.getElementById('composerPlaceholderGhost');
const sendBtn = document.getElementById('sendBtn');
const micBtn = document.getElementById('micBtn');
const apiBaseInput = document.getElementById('apiBaseInput');
const saveApiBtn = document.getElementById('saveApiBtn');
const menuClearBtn = document.getElementById('menuClearBtn');
const menuNewChatBtn = document.getElementById('menuNewChatBtn');
const menuChatsBtn = document.getElementById('menuChatsBtn');
const menuThemeBtn = document.getElementById('menuThemeBtn');
const menuThemeIconWrap = document.getElementById('menuThemeIconWrap');
const menuThemeDesc = document.getElementById('menuThemeDesc');
const topbarMenu = document.getElementById('topbarMenu');
const topbarMenuTrigger = document.getElementById('topbarMenuTrigger');
const pageContextTitleEl = document.getElementById('pageContextTitle');
const pageContextMetaEl = document.getElementById('pageContextMeta');
const refreshPageContextBtn = document.getElementById('refreshPageContextBtn');
const usePageContextToggle = document.getElementById('usePageContextToggle');
const chatPicker = document.getElementById('chatPicker');
const chatPickerBackdrop = document.getElementById('chatPickerBackdrop');
const chatPickerClose = document.getElementById('chatPickerClose');
const newChatBtn = document.getElementById('newChatBtn');
const chatPickerList = document.getElementById('chatPickerList');
const chatPickerStatus = document.getElementById('chatPickerStatus');

const STORAGE_MESSAGES = 'assistant_messages';
const STORAGE_API_BASE = 'api_base_url';
const STORAGE_CONVERSATION = 'conversation_id';
const STORAGE_THEME = 'ui_theme';
const STORAGE_USE_PAGE_CONTEXT = 'use_page_context';
const DEFAULT_API_BASE = 'https://api.logisticopilot.com';
const CHAT_PICKER_TRANSITION_MS = 260;
/** Default two lines: 14.5px * 1.45 * 2 + padding 11+10 ≈ 64px */
const COMPOSER_TEXTAREA_MIN_PX = 64;
/** Max height when draft grows (several lines). */
const COMPOSER_TEXTAREA_MAX_PX = 110;
const MAX_TRANSCRIPTION_BYTES = 25 * 1024 * 1024;

/** Baseline when no hint is shown; native placeholder stays visually hidden (see ghost layer). */
const DEFAULT_PLACEHOLDER_TEXT = '';
const PLACEHOLDER_TYPE_MS = 48;
const PLACEHOLDER_TYPE_JITTER_MS = 24;
const PLACEHOLDER_DELETE_MS = 22;
const PLACEHOLDER_DELETE_JITTER_MS = 14;
const PLACEHOLDER_PAUSE_AFTER_FULL_MS = 30_000;
const PLACEHOLDER_INITIAL_DELAY_MS = 1_000;
const PLACEHOLDER_GAP_BETWEEN_PHRASES_MS = 400;

/** Example prompts aligned with freight tools: overview, shipments, bids, quotes, archive, TMS, browser context */
const LOGISTIC_DASHBOARD_PLACEHOLDERS = [
  'Give me a freight pipeline overview: counts by stage…',
  "What's on the dashboard today — hot loads first…",
  'List shipments that need attention before end of day…',
  'Show today’s loads and which are still in quoting…',
  'Search shipments mentioning Chicago and summarize…',
  'Find loads stuck in carrier review and why…',
  'Diagnose what is blocking shipment Q-87845634…',
  'Pull a brief for quote token Q-87845634 before I call the client…',
  'Summarize the case for this quote token from email context…',
  'Get shipment thread excerpt for the load I’m viewing…',
  'Compare margin defaults vs what we quoted last week…',
  'Run freight_domain_foundation and explain stages in plain English…',
  'List workflow events for the noisiest shipment this week…',
  'Which carriers have bids pending review?…',
  'Evaluate bids for the shipment I paste next — dry run first…',
  'Draft a customer quote dry run for this lane…',
  'Handoff to TMS as dry_run — show what would happen…',
  'Carrier outreach dry run for cold leads on this route…',
  'Search archived shipments suppressed last month…',
  'Archived case summary for old quote token…',
  'List clients with default margin above 12%…',
  'List active carriers in the southeast region…',
  'Loads by city: Atlanta inbound this week…',
  'What loads are scheduled for pickup tomorrow morning?…',
  'Explain correlation: subject token vs provider thread id…',
  'When should I use diagnose vs full thread transcript?…',
  'Ready to update delivery window — only if user confirms…',
  'Browser: summarize the open TMS page and tie it to our shipment…',
  'Use page excerpt + find matching shipment in freight DB…',
  'What does freight_get_overview return right now?…',
  'Stage distribution: quoting vs booked vs in transit…',
  'Flag shipments missing ready_at_local…',
  'Archive reason codes — which apply to this thread?…',
  'Dry-run archive shipment — do not execute for real…',
  'Intake this carrier bid JSON — validate fields…',
  'After bid intake, what workflow event should fire?…',
  'Show me list_today_shipments vs search_shipments difference…',
  'Risk: loads with no carrier response in 48h…',
  'Quote follow-up email angle for a stalled bid…',
  'Normalize pickup/delivery local times for this route…',
  'Outlook-driven state — where is this shipment in the graph?…',
  'Prepare operator checklist before sending real quote…',
  'Funnel snapshot: quotes vs bookings vs risks…',
  'Today’s shipments and what needs a decision…',
  'Diagnose shipment by token Q-… — what is blocking…',
  'Find archived shipments with suppress and summarize…',
  'Dry-run TMS handoff for this order…',
  'Compare dry_run customer quote vs actual shipment fields…',
  'From the current browser tab — extract the address and match it in freight…',
  'Carrier outreach copy — dry run, no send…',
  'Workflow events for this shipment — last 20…',
  'Margin policy defaults vs realized margin for this client…',
  'List shipments where delivery_at_local is next Tuesday…',
  'What changed on the board since yesterday 17:00 UTC?…',
  'Generate a one-screen ops brief I can paste into Slack…',
];

let placeholderLoopActive = true;
let placeholderTypewriterPaused = false;
let lastPlaceholderExample = '';
/** Full phrase for the current typewriter cycle (used to fill draft on double-click / long-press). */
let activeTypewriterPhraseFull = '';
const _phTimeoutIds = [];
const PLACEHOLDER_LONG_PRESS_MS = 520;
let _placeholderPressTimer = null;
let _placeholderPressDownX = 0;
let _placeholderPressDownY = 0;
let _placeholderPressTracking = false;

function _phDelay(ms) {
  return new Promise((resolve) => {
    const id = setTimeout(() => {
      const ix = _phTimeoutIds.indexOf(id);
      if (ix >= 0) _phTimeoutIds.splice(ix, 1);
      resolve();
    }, ms);
    _phTimeoutIds.push(id);
  });
}

function clearPlaceholderTypewriterTimers() {
  _phTimeoutIds.forEach(clearTimeout);
  _phTimeoutIds.length = 0;
}

function refreshPlaceholderTypewriterPause() {
  placeholderTypewriterPaused =
    document.activeElement === userInput || Boolean(userInput.value && userInput.value.trim());
}

/** Visual hint while the native placeholder is transparent (UAs often hide it on :focus). */
function syncComposerPlaceholderGhost() {
  if (!composerPlaceholderGhost || !userInput) return;
  const hasDraft = Boolean(userInput.value && userInput.value.trim());
  composerPlaceholderGhost.hidden = hasDraft;
  if (!hasDraft) {
    composerPlaceholderGhost.textContent = userInput.placeholder || '';
  }
}

function pickRandomLogisticPlaceholder() {
  const arr = LOGISTIC_DASHBOARD_PLACEHOLDERS;
  if (!arr.length) return '';
  if (arr.length === 1) return arr[0];
  let pick = arr[0];
  for (let attempt = 0; attempt < 10; attempt++) {
    pick = arr[Math.floor(Math.random() * arr.length)];
    if (pick !== lastPlaceholderExample) break;
  }
  lastPlaceholderExample = pick;
  return pick;
}

async function runPlaceholderTypewriterLoop() {
  await _phDelay(PLACEHOLDER_INITIAL_DELAY_MS);
  while (placeholderLoopActive) {
    while (placeholderLoopActive) {
      refreshPlaceholderTypewriterPause();
      if (!placeholderLoopActive) break;
      if (!placeholderTypewriterPaused) break;
      await _phDelay(320);
    }
    if (!placeholderLoopActive) break;
    const phrase = pickRandomLogisticPlaceholder();
    activeTypewriterPhraseFull = phrase;
    if (!phrase.length) {
      await _phDelay(PLACEHOLDER_GAP_BETWEEN_PHRASES_MS);
      continue;
    }
    for (let i = 1; i <= phrase.length; i++) {
      if (!placeholderLoopActive) return;
      refreshPlaceholderTypewriterPause();
      if (placeholderTypewriterPaused) break;
      userInput.placeholder = phrase.slice(0, i);
      autoResize();
      await _phDelay(PLACEHOLDER_TYPE_MS + Math.random() * PLACEHOLDER_TYPE_JITTER_MS);
    }
    refreshPlaceholderTypewriterPause();
    if (placeholderTypewriterPaused) {
      if (userInput.value.trim()) {
        userInput.placeholder = DEFAULT_PLACEHOLDER_TEXT;
      }
      autoResize();
      continue;
    }
    await _phDelay(PLACEHOLDER_PAUSE_AFTER_FULL_MS);
    if (!placeholderLoopActive) break;
    while (placeholderLoopActive) {
      refreshPlaceholderTypewriterPause();
      if (!placeholderLoopActive) break;
      if (!placeholderTypewriterPaused) break;
      await _phDelay(320);
    }
    for (let i = phrase.length; i >= 0; i--) {
      if (!placeholderLoopActive) return;
      refreshPlaceholderTypewriterPause();
      if (placeholderTypewriterPaused) break;
      userInput.placeholder = i === 0 ? DEFAULT_PLACEHOLDER_TEXT : phrase.slice(0, i);
      autoResize();
      await _phDelay(PLACEHOLDER_DELETE_MS + Math.random() * PLACEHOLDER_DELETE_JITTER_MS);
    }
    refreshPlaceholderTypewriterPause();
    if (placeholderTypewriterPaused) {
      if (userInput.value.trim()) {
        userInput.placeholder = DEFAULT_PLACEHOLDER_TEXT;
      }
      autoResize();
      continue;
    }
    userInput.placeholder = DEFAULT_PLACEHOLDER_TEXT;
    autoResize();
    await _phDelay(PLACEHOLDER_GAP_BETWEEN_PHRASES_MS + Math.random() * 280);
  }
}

let TOOL_NAME_LABELS = {
  freight_update_shipment_details_by_token: 'Update shipment details',
  freight_get_shipment_by_token: 'Get shipment',
};

const SEND_ICON = `
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
  <path d="M12 19V5"></path><path d="M5 12l7-7 7 7"></path>
</svg>`;
const MIC_ICON = `
<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" aria-hidden="true">
  <rect x="9" y="3" width="6" height="11" rx="3"></rect><path d="M5 11a7 7 0 0 0 14 0"></path><path d="M12 18v3"></path><path d="M8 21h8"></path>
</svg>`;
const MIC_STOP_ICON = `
<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
  <rect x="6.4" y="6.4" width="11.2" height="11.2" rx="2.2"></rect>
</svg>`;
const COPY_ICON = `
<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
  <rect x="9" y="9" width="10" height="10" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path>
</svg>`;
const COPY_DONE_ICON = `
<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
  <path d="M5 13l4 4L19 7"></path>
</svg>`;
const STOP_ICON = `
<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
  <rect x="6.4" y="6.4" width="11.2" height="11.2" rx="2.2"></rect>
</svg>`;

let currentPageContext = null;

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

function closeTopbarMenu() {
  if (topbarMenu instanceof HTMLDetailsElement) topbarMenu.open = false;
}

function updateThemeButton(theme) {
  const isLight = theme === 'light';
  const icon = isLight ? THEME_ICON_MOON : THEME_ICON_SUN;
  if (menuThemeIconWrap) menuThemeIconWrap.innerHTML = icon;
  const title = isLight ? 'Switch to dark theme' : 'Switch to light theme';
  if (menuThemeBtn) {
    menuThemeBtn.title = title;
    menuThemeBtn.setAttribute('aria-label', title);
  }
  if (menuThemeDesc) {
    menuThemeDesc.textContent = isLight ? 'Light theme — tap to use dark' : 'Dark theme — tap to use light';
  }
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
  menuThemeBtn?.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    applyTheme(cur === 'light' ? 'dark' : 'light', true);
    closeTopbarMenu();
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

function loadUsePageContext(callback) {
  chrome.storage.local.get([STORAGE_USE_PAGE_CONTEXT], (result) => {
    callback(result[STORAGE_USE_PAGE_CONTEXT] !== false);
  });
}

function saveUsePageContext(enabled) {
  chrome.storage.local.set({ [STORAGE_USE_PAGE_CONTEXT]: Boolean(enabled) });
}

function scrollToBottom() {
  const el = messagesEl;
  const top = el.scrollHeight;
  if (typeof el.scrollTo === 'function') {
    try {
      el.scrollTo({ top, behavior: 'instant' });
    } catch {
      el.scrollTop = top;
    }
  } else {
    el.scrollTop = top;
  }
}

function clearThreadTurns() {
  messagesEl.querySelectorAll('article.turn').forEach((el) => el.remove());
}

/** @param {string | undefined} iso */
function parseMessageTime(iso) {
  if (!iso || typeof iso !== 'string') return getTime();
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? getTime() : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** @param {string | undefined} iso */
function formatListDate(iso) {
  if (!iso || typeof iso !== 'string') return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** @param {string} apiBase @param {AbortSignal} signal */
async function fetchConversationsList(apiBase, signal) {
  const res = await fetch(`${apiBase}/api/conversations`, { signal });
  if (!res.ok) {
    const t = await res.text().catch(() => '');
    throw new Error(t || `HTTP ${res.status}`);
  }
  return res.json();
}

/** @param {string} apiBase @param {string} conversationId @param {AbortSignal} signal */
async function fetchConversationMessages(apiBase, conversationId, signal) {
  const url = `${apiBase}/api/conversations/${encodeURIComponent(conversationId)}/messages`;
  const res = await fetch(url, { signal });
  if (!res.ok) {
    const t = await res.text().catch(() => '');
    throw new Error(t || `HTTP ${res.status}`);
  }
  return res.json();
}

/** @param {string} apiBase @param {string} conversationId */
async function deleteConversationOnServer(apiBase, conversationId) {
  const url = `${apiBase}/api/conversations/${encodeURIComponent(conversationId)}`;
  const res = await fetch(url, { method: 'DELETE' });
  if (res.status === 204) return;
  const t = await res.text().catch(() => '');
  throw new Error(t || `HTTP ${res.status}`);
}

const ROW_MORE_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.75"/><circle cx="12" cy="12" r="1.75"/><circle cx="12" cy="19" r="1.75"/></svg>`;

/** @param {Array<{ role: string, content?: string, created_at?: string }>} rows */
function buildHistoryFromServerMessages(rows) {
  const hist = [];
  for (const m of rows) {
    const time = parseMessageTime(m.created_at);
    const content = typeof m.content === 'string' ? m.content : '';
    if (m.role === 'user') {
      appendUserTurn(content, time);
      hist.push({ role: 'user', text: content, time });
    } else if (m.role === 'assistant') {
      const segments = [{ type: 'text', text: content }];
      renderAssistantFromSegments(segments, time);
      hist.push({ role: 'assistant', time, segments, text: content });
    }
  }
  return hist;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function pageContextSummary(snapshot) {
  if (!snapshot || snapshot.available === false) {
    return {
      title: 'Current tab is unavailable',
      meta: snapshot?.unavailable_reason || 'This tab cannot be read right now. Refresh after switching to a normal webpage.',
    };
  }
  const title = snapshot?.title || snapshot?.url || 'Current page connected';
  let domain = '';
  try {
    domain = snapshot?.url ? new URL(snapshot.url).hostname : '';
  } catch {
    domain = snapshot?.origin || '';
  }
  const captured = snapshot?.captured_at ? new Date(snapshot.captured_at) : null;
  const capturedLabel =
    captured && !Number.isNaN(captured.getTime())
      ? `Updated ${captured.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
      : 'Waiting for page snapshot';
  const pageHint = snapshot?.page_type_hint ? ` · ${snapshot.page_type_hint.replace(/_/g, ' ')}` : '';
  return {
    title,
    meta: `${domain || 'No domain'} · ${capturedLabel}${pageHint}`,
  };
}

function renderPageContext(snapshot) {
  currentPageContext = snapshot || null;
  const summary = pageContextSummary(snapshot);
  if (pageContextTitleEl) pageContextTitleEl.textContent = summary.title;
  if (pageContextMetaEl) pageContextMetaEl.textContent = summary.meta;
}

function shouldAttachPageHint(text) {
  const haystack = String(text || '').toLowerCase();
  return /(this page|current page|current tab|open page|open tab|that page|screen|form|what is on the page|look at the page|analyze the page|работай с текущей страницей|текущая страница|текущая вкладка|страниц[аеу]|вкладк[аеу]|что на странице|посмотри страницу|проанализируй страницу|заполни по странице)/i.test(
    haystack
  );
}

async function requestCurrentPageContext(forceRefresh) {
  const message = { type: forceRefresh ? 'CAPTURE_CURRENT_PAGE' : 'GET_CURRENT_PAGE_CONTEXT' };
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({
          available: false,
          unavailable_reason: chrome.runtime.lastError.message || 'Failed to load current page context.',
        });
        return;
      }
      const payload = response?.payload || null;
      if (payload) {
        resolve(payload);
        return;
      }
      if (!forceRefresh) {
        chrome.runtime.sendMessage({ type: 'CAPTURE_CURRENT_PAGE' }, (captureResponse) => {
          if (chrome.runtime.lastError) {
            resolve({
              available: false,
              unavailable_reason: chrome.runtime.lastError.message || 'Failed to capture current page context.',
            });
            return;
          }
          resolve(captureResponse?.payload || null);
        });
        return;
      }
      resolve(null);
    });
  });
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

function normalizeCopyText(text) {
  return String(text || '')
    .replace(/\s+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function extractCopyTextFromFlow(flow) {
  if (!flow) return '';
  return normalizeCopyText(flow.innerText || flow.textContent || '');
}

function createTurnFooter(timeText, getCopyText) {
  const footer = document.createElement('div');
  footer.className = 'turn-footer';

  const meta = document.createElement('time');
  meta.className = 'turn-meta';
  meta.textContent = timeText || getTime();
  footer.appendChild(meta);

  if (typeof getCopyText === 'function') {
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'turn-copy-btn';
    copyBtn.innerHTML = COPY_ICON;
    copyBtn.title = 'Copy message';
    copyBtn.setAttribute('aria-label', 'Copy message');
    copyBtn.addEventListener('click', async () => {
      const content = normalizeCopyText(getCopyText());
      if (!content) return;
      try {
        await navigator.clipboard.writeText(content);
        copyBtn.classList.add('is-copied');
        copyBtn.innerHTML = COPY_DONE_ICON;
        setTimeout(() => {
          copyBtn.classList.remove('is-copied');
          copyBtn.innerHTML = COPY_ICON;
        }, 900);
      } catch (err) {
        console.warn('Clipboard copy failed', err);
      }
    });
    footer.appendChild(copyBtn);
  }
  return footer;
}

function formatToolLabel(toolName) {
  if (!toolName) return 'Tool';
  const key = String(toolName).trim();
  if (TOOL_NAME_LABELS[key]) return TOOL_NAME_LABELS[key];
  const normalized = key
    .replace(/^freight_/, '')
    .replace(/^tool_/, '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!normalized) return key;
  return normalized.replace(/\b\w/g, (c) => c.toUpperCase());
}

async function loadToolLabelsFromBackend() {
  try {
    const apiBase = await loadApiBaseValue();
    const response = await fetch(`${apiBase}/api/tools/metadata`);
    if (!response.ok) return;
    const payload = await response.json().catch(() => null);
    const labels = payload?.tool_labels;
    if (!labels || typeof labels !== 'object') return;
    let updated = false;
    for (const [name, label] of Object.entries(labels)) {
      if (typeof name !== 'string' || typeof label !== 'string') continue;
      const normalizedName = name.trim();
      const normalizedLabel = label.trim();
      if (!normalizedName || !normalizedLabel) continue;
      TOOL_NAME_LABELS[normalizedName] = normalizedLabel;
      updated = true;
    }
    if (updated) {
      const rendered = messagesEl.querySelectorAll('.inline-tool');
      for (const aside of rendered) {
        const ref = aside?._tool;
        const nameNode = aside.querySelector('.inline-tool__name');
        if (ref && nameNode) nameNode.textContent = formatToolLabel(ref.tool);
      }
    }
  } catch (err) {
    console.warn('Failed to load tool labels from backend metadata', err);
  }
}

/** Wrap top-level GFM tables for horizontal scroll + panel chrome (DOMPurify keeps div). */
function wrapMarkdownTables(html) {
  if (!html || !html.includes('<table')) return html;
  const host = document.createElement('div');
  host.innerHTML = html;
  for (const child of [...host.children]) {
    if (child.tagName !== 'TABLE') continue;
    const wrap = document.createElement('div');
    wrap.className = 'markdown-table-wrap';
    child.replaceWith(wrap);
    wrap.appendChild(child);
  }
  return host.innerHTML;
}

function renderMarkdown(text) {
  const raw = text == null ? '' : String(text);
  if (!raw.trim()) return '<p class="text-muted">…</p>';
  const unsafe = parseMarkdownToUnsafeHtml(raw);
  const withTableWrap = unsafe != null ? wrapMarkdownTables(unsafe) : null;
  if (withTableWrap != null && typeof DOMPurify !== 'undefined') {
    try {
      return DOMPurify.sanitize(withTableWrap, { USE_PROFILES: { html: true } });
    } catch (e) {
      console.warn('DOMPurify.sanitize failed', e);
      try {
        return DOMPurify.sanitize(withTableWrap);
      } catch (e2) {
        console.warn('DOMPurify fallback failed', e2);
      }
    }
  }
  if (withTableWrap != null && typeof DOMPurify === 'undefined') {
    return withTableWrap;
  }
  console.warn('Markdown parser unavailable; plain text fallback');
  return `<p>${escapeHtml(raw).replace(/\n/g, '<br>')}</p>`;
}

/**
 * Raw markdown for a streaming / finalized prose block (innerHTML is rendered; this preserves source).
 * @param {HTMLElement} el
 */
function streamPlainSourceText(el) {
  const raw = /** @type {{ _streamRaw?: string }} */ (el)._streamRaw;
  if (typeof raw === 'string') return raw;
  return el.textContent || '';
}

/** @param {HTMLElement} el */
function setStreamPlainMarkdown(el, rawMarkdown) {
  const raw = rawMarkdown == null ? '' : String(rawMarkdown);
  /** @type {{ _streamRaw?: string }} */ (el)._streamRaw = raw;
  el.innerHTML = renderMarkdown(raw);
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
  const titleWrap = document.createElement('span');
  titleWrap.className = 'inline-tool__title';
  const name = document.createElement('span');
  name.className = 'inline-tool__name';
  name.textContent = formatToolLabel(tool.tool);
  titleWrap.appendChild(name);
  const pill = document.createElement('span');
  pill.className =
    'inline-tool__pill ' + (tool.status === 'running' ? 'inline-tool__pill--run' : 'inline-tool__pill--done');
  pill.textContent = tool.status === 'running' ? 'Running' : 'Done';
  bar.appendChild(glyph);
  bar.appendChild(titleWrap);
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
  article.appendChild(line);
  article.appendChild(createTurnFooter(time || getTime(), () => text));
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
  const meta = createTurnFooter(time || getTime(), () => extractCopyTextFromFlow(flow));
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

async function streamChat(apiBase, conversationId, userText, onToken, onEvent, signal) {
  const url = `${apiBase}/api/chat`;
  const browserContextPayload =
    usePageContextToggle?.checked && currentPageContext
      ? {
          page_snapshot: currentPageContext,
          attach_hint: shouldAttachPageHint(userText),
        }
      : undefined;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      content: userText,
      conversation_id: conversationId || undefined,
      browser_context: browserContextPayload,
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
      const raw = streamPlainSourceText(el);
      el.className = 'markdown-body';
      if (raw.trim()) {
        el.innerHTML = renderMarkdown(raw);
      } else {
        el.remove();
      }
      delete /** @type {{ _streamRaw?: string }} */ (el)._streamRaw;
    }
    if (el.classList.contains('inline-tool')) {
      const det = el.querySelector('details.inline-tool__drawer');
      if (det) det.open = false;
    }
  }
}

let history = [];
let conversationId = null;
let isSending = false;
let isRecording = false;
let isTranscribing = false;
let sendAfterTranscription = false;
let mediaRecorder = null;
let mediaStream = null;
let recordedMimeType = 'audio/webm';
let recordedChunks = [];
let activeChatAbortController = null;
let activeTranscriptionAbortController = null;
let chatPickerListAbortController = null;

function stopMediaStream() {
  if (!mediaStream) return;
  for (const track of mediaStream.getTracks()) {
    track.stop();
  }
  mediaStream = null;
}

function setUserInputValue(text) {
  userInput.value = text;
  autoResize();
}

function appendSystemNote(message) {
  appendAssistantTurn(message, getTime(), null);
  history.push({
    role: 'assistant',
    time: getTime(),
    segments: [{ type: 'text', text: message }],
    text: message,
  });
  saveMessages(history);
}

function updateComposerControls() {
  if (sendBtn) {
    sendBtn.classList.toggle('is-stop', isSending || isTranscribing);
    if (isSending) {
      sendBtn.title = 'Stop response';
      sendBtn.setAttribute('aria-label', 'Stop response');
      sendBtn.innerHTML = STOP_ICON;
    } else if (isTranscribing) {
      sendBtn.title = 'Cancel transcription';
      sendBtn.setAttribute('aria-label', 'Cancel transcription');
      sendBtn.innerHTML = STOP_ICON;
    } else if (isRecording) {
      sendBtn.title = 'Transcribe and send';
      sendBtn.setAttribute('aria-label', 'Transcribe and send');
      sendBtn.innerHTML = SEND_ICON;
    } else {
      sendBtn.title = 'Send';
      sendBtn.setAttribute('aria-label', 'Send');
      sendBtn.innerHTML = SEND_ICON;
    }
    sendBtn.disabled = false;
  }
  if (micBtn) {
    micBtn.classList.toggle('is-recording', isRecording);
    micBtn.classList.toggle('is-transcribing', isTranscribing);
    micBtn.disabled = isSending;
    if (isRecording) {
      micBtn.title = 'Stop recording';
      micBtn.setAttribute('aria-label', 'Stop recording');
      micBtn.innerHTML = MIC_STOP_ICON;
    } else if (isTranscribing) {
      micBtn.title = 'Transcribing… click to cancel';
      micBtn.setAttribute('aria-label', 'Cancel transcription');
      micBtn.innerHTML = MIC_STOP_ICON;
    } else {
      micBtn.title = 'Start voice dictation';
      micBtn.setAttribute('aria-label', 'Start voice dictation');
      micBtn.innerHTML = MIC_ICON;
    }
  }
  syncComposerFilledButtons();
}

async function loadApiBaseValue() {
  return await new Promise((resolve) => {
    loadApiBase((base) => resolve(base));
  });
}

function abortCurrentChat() {
  if (activeChatAbortController) {
    activeChatAbortController.abort();
  }
}

function cancelTranscription() {
  if (activeTranscriptionAbortController) {
    activeTranscriptionAbortController.abort();
  }
  sendAfterTranscription = false;
}

async function startVoiceRecording() {
  if (isSending || isTranscribing || isRecording) return;
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    appendSystemNote('Voice dictation is not available in this browser environment.');
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    recordedMimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
    mediaRecorder = MediaRecorder.isTypeSupported(recordedMimeType)
      ? new MediaRecorder(mediaStream, { mimeType: recordedMimeType })
      : new MediaRecorder(mediaStream);
    mediaRecorder.addEventListener('dataavailable', (event) => {
      if (event.data && event.data.size > 0) recordedChunks.push(event.data);
    });
    mediaRecorder.start();
    isRecording = true;
    sendAfterTranscription = false;
    updateComposerControls();
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    appendSystemNote(`Unable to start voice recording: ${reason}`);
    stopMediaStream();
  }
}

async function stopRecordingAndCollectBlob() {
  if (!mediaRecorder || mediaRecorder.state === 'inactive') return null;
  return await new Promise((resolve) => {
    const recorder = mediaRecorder;
    recorder.addEventListener(
      'stop',
      () => {
        const chunks = recordedChunks.slice();
        recordedChunks = [];
        mediaRecorder = null;
        stopMediaStream();
        if (!chunks.length) {
          resolve(null);
          return;
        }
        const mimeType = (recorder.mimeType || recordedMimeType || 'audio/webm').split(';')[0];
        resolve(new Blob(chunks, { type: mimeType }));
      },
      { once: true }
    );
    recorder.stop();
  });
}

async function transcribeAudioBlob(blob) {
  if (!blob || blob.size <= 0) return '';
  if (blob.size > MAX_TRANSCRIPTION_BYTES) {
    appendSystemNote('Voice message is too large for transcription (max 25 MB).');
    return '';
  }
  const apiBase = await loadApiBaseValue();
  const controller = new AbortController();
  activeTranscriptionAbortController = controller;
  isTranscribing = true;
  updateComposerControls();
  try {
    const fileExtension = blob.type.includes('wav') ? 'wav' : blob.type.includes('mp4') ? 'mp4' : 'webm';
    const formData = new FormData();
    formData.append('file', blob, `voice-note.${fileExtension}`);
    formData.append('language', 'en');
    const response = await fetch(`${apiBase}/api/audio/transcriptions`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
    if (!response.ok) {
      const details = await response.text().catch(() => '');
      throw new Error(`HTTP ${response.status}: ${details || response.statusText}`);
    }
    const payload = await response.json().catch(() => ({}));
    return typeof payload?.text === 'string' ? payload.text.trim() : '';
  } finally {
    if (activeTranscriptionAbortController === controller) {
      activeTranscriptionAbortController = null;
    }
    isTranscribing = false;
    updateComposerControls();
  }
}

async function finalizeRecordingAndTranscribe(shouldSendAfter) {
  if (!isRecording) return;
  isRecording = false;
  sendAfterTranscription = sendAfterTranscription || Boolean(shouldSendAfter);
  updateComposerControls();
  const blob = await stopRecordingAndCollectBlob();
  if (!blob) {
    sendAfterTranscription = false;
    return;
  }
  try {
    const transcript = await transcribeAudioBlob(blob);
    const text = transcript.trim();
    if (!text) {
      sendAfterTranscription = false;
      return;
    }
    setUserInputValue(text);
    if (sendAfterTranscription) {
      sendAfterTranscription = false;
      await sendMessage();
      return;
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      return;
    }
    const message = err instanceof Error ? err.message : String(err);
    appendSystemNote(`Voice transcription failed: ${message}`);
  } finally {
    sendAfterTranscription = false;
    updateComposerControls();
  }
}

function discardRecordingSilently() {
  if (!isRecording) return;
  isRecording = false;
  sendAfterTranscription = false;
  updateComposerControls();
  const recorder = mediaRecorder;
  if (recorder && recorder.state !== 'inactive') {
    recorder.addEventListener(
      'stop',
      () => {
        recordedChunks = [];
        mediaRecorder = null;
        stopMediaStream();
      },
      { once: true }
    );
    recorder.stop();
  } else {
    recordedChunks = [];
    mediaRecorder = null;
    stopMediaStream();
  }
}

let chatPickerHideTimer = null;

function setChatPickerOpen(open) {
  if (!chatPicker) return;
  if (open) {
    if (chatPickerHideTimer) {
      clearTimeout(chatPickerHideTimer);
      chatPickerHideTimer = null;
    }
    chatPicker.removeAttribute('hidden');
    chatPicker.setAttribute('aria-hidden', 'false');
    chatPicker.classList.remove('chat-picker--open');
    void chatPicker.offsetWidth;
    requestAnimationFrame(() => {
      chatPicker.classList.add('chat-picker--open');
    });
    chatPickerClose?.focus({ preventScroll: true });
  } else {
    chatPicker.classList.remove('chat-picker--open');
    chatPicker.setAttribute('aria-hidden', 'true');
    chatPickerListAbortController?.abort();
    chatPickerListAbortController = null;
    if (chatPickerHideTimer) clearTimeout(chatPickerHideTimer);
    chatPickerHideTimer = setTimeout(() => {
      chatPicker.setAttribute('hidden', '');
      chatPickerHideTimer = null;
    }, CHAT_PICKER_TRANSITION_MS);
    topbarMenuTrigger?.focus({ preventScroll: true });
  }
}

function setChatPickerStatus(msg, isError) {
  if (!chatPickerStatus) return;
  if (!msg) {
    chatPickerStatus.setAttribute('hidden', '');
    chatPickerStatus.textContent = '';
    chatPickerStatus.classList.remove('chat-picker-status--error');
    return;
  }
  chatPickerStatus.removeAttribute('hidden');
  chatPickerStatus.textContent = msg;
  chatPickerStatus.classList.toggle('chat-picker-status--error', Boolean(isError));
}

/**
 * @param {string} id
 * @param {HTMLDetailsElement | null} menuDetails
 */
async function handleDeleteConversationFromDrawer(id, menuDetails) {
  if (!id) return;
  if (!confirm('Delete this conversation permanently? This cannot be undone.')) return;
  if (menuDetails) menuDetails.open = false;
  try {
    const apiBase = await loadApiBaseValue();
    await deleteConversationOnServer(apiBase, id);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    setChatPickerStatus(`Could not delete: ${msg}`, true);
    return;
  }
  setChatPickerStatus('', false);
  const wrap = menuDetails?.closest('.chat-picker-row-wrap');
  if (wrap) wrap.remove();
  const deletedWasCurrent = conversationId && String(conversationId) === String(id);
  if (deletedWasCurrent) {
    conversationId = null;
    chrome.storage.local.remove([STORAGE_CONVERSATION]);
    history = [];
    clearThreadTurns();
    saveMessages([]);
  }
  if (chatPickerList && !chatPickerList.querySelector('.chat-picker-row-wrap')) {
    const empty = document.createElement('p');
    empty.className = 'chat-picker-empty';
    empty.textContent = 'No conversations yet. Send a message to start one.';
    chatPickerList.appendChild(empty);
  }
}

/** @param {Array<{ id: string, title?: string, created_at?: string, message_count?: number }>} conversations */
function renderConversationRows(conversations) {
  if (!chatPickerList) return;
  chatPickerList.innerHTML = '';
  const cur = conversationId ? String(conversationId) : null;
  if (!conversations.length) {
    const empty = document.createElement('p');
    empty.className = 'chat-picker-empty';
    empty.textContent = 'No conversations yet. Send a message to start one.';
    chatPickerList.appendChild(empty);
    return;
  }
  for (const c of conversations) {
    const id = String(c.id);
    const wrap = document.createElement('div');
    wrap.className = 'chat-picker-row-wrap';
    if (cur && cur === id) wrap.classList.add('chat-picker-row-wrap--active');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chat-picker-row';
    btn.dataset.conversationId = id;
    const title = document.createElement('span');
    title.className = 'chat-picker-row-title';
    title.textContent = (c.title && String(c.title).trim()) || 'Untitled chat';
    const meta = document.createElement('span');
    meta.className = 'chat-picker-row-meta';
    const n = typeof c.message_count === 'number' ? c.message_count : 0;
    const dateLabel = formatListDate(c.created_at) || '';
    meta.textContent = dateLabel ? `${n} messages · ${dateLabel}` : `${n} messages`;
    btn.appendChild(title);
    btn.appendChild(meta);
    btn.addEventListener('click', () => {
      void selectConversationFromServer(id);
    });

    const actions = document.createElement('details');
    actions.className = 'chat-picker-row-menu';
    const sum = document.createElement('summary');
    sum.className = 'chat-picker-row-more';
    sum.setAttribute('aria-label', 'More actions for this chat');
    sum.innerHTML = ROW_MORE_ICON;
    const panel = document.createElement('div');
    panel.className = 'chat-picker-row-menu-panel';
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'chat-picker-row-delete';
    delBtn.textContent = 'Delete conversation…';
    delBtn.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      void handleDeleteConversationFromDrawer(id, actions);
    });
    panel.appendChild(delBtn);
    actions.appendChild(sum);
    actions.appendChild(panel);
    actions.addEventListener('toggle', () => {
      if (!actions.open) return;
      chatPickerList?.querySelectorAll('details.chat-picker-row-menu').forEach((d) => {
        if (d !== actions && d instanceof HTMLDetailsElement) d.open = false;
      });
    });

    wrap.appendChild(btn);
    wrap.appendChild(actions);
    chatPickerList.appendChild(wrap);
  }
}

async function refreshChatPickerList() {
  setChatPickerStatus('', false);
  chatPickerListAbortController?.abort();
  chatPickerListAbortController = new AbortController();
  const signal = chatPickerListAbortController.signal;
  if (chatPickerList) chatPickerList.innerHTML = '';
  setChatPickerStatus('Loading…', false);
  try {
    const apiBase = await loadApiBaseValue();
    const list = await fetchConversationsList(apiBase, signal);
    setChatPickerStatus('', false);
    renderConversationRows(Array.isArray(list) ? list : []);
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    const msg = e instanceof Error ? e.message : String(e);
    setChatPickerStatus(`Could not load chats: ${msg}`, true);
    if (chatPickerList) chatPickerList.innerHTML = '';
  }
}

async function selectConversationFromServer(id) {
  if (!id) return;
  abortCurrentChat();
  cancelTranscription();
  discardRecordingSilently();
  chatPickerListAbortController?.abort();
  const ctrl = new AbortController();
  chatPickerListAbortController = ctrl;
  const signal = ctrl.signal;
  setChatPickerStatus('Loading messages…', false);
  try {
    const apiBase = await loadApiBaseValue();
    const rows = await fetchConversationMessages(apiBase, id, signal);
    clearThreadTurns();
    history = buildHistoryFromServerMessages(Array.isArray(rows) ? rows : []);
    conversationId = id;
    saveConversationId(id);
    saveMessages(history);
    setChatPickerOpen(false);
    scrollToBottom();
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    const msg = e instanceof Error ? e.message : String(e);
    setChatPickerStatus(`Could not open chat: ${msg}`, true);
    void refreshChatPickerList();
  }
}

function startNewChatFromPicker() {
  abortCurrentChat();
  cancelTranscription();
  discardRecordingSilently();
  conversationId = null;
  chrome.storage.local.remove([STORAGE_CONVERSATION]);
  history = [];
  clearThreadTurns();
  saveMessages([]);
  setChatPickerOpen(false);
}

async function sendMessage() {
  if (isSending || isRecording || isTranscribing) return;
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

  if (usePageContextToggle?.checked) {
    try {
      const freshSnapshot = await requestCurrentPageContext(true);
      renderPageContext(freshSnapshot);
    } catch (err) {
      console.warn('Failed to refresh page context before sending message', err);
    }
  }

  let pendingText = '';
  /** @type {{ tool: string, status: string, toolInput?: object, toolOutput?: string }[]} */
  const toolsLog = [];
  /** @type {HTMLElement[]} */
  const toolAsides = [];

  /** @type {HTMLElement | null} */
  let streamArticle = null;
  /** @type {HTMLElement | null} */
  let streamBody = null;

  let streamTailMdRaf = 0;
  function flushStreamTailMarkdown() {
    streamTailMdRaf = 0;
    if (!streamBody) return;
    const tail = streamBody.querySelector('.stream-plain--tail');
    if (!tail) return;
    setStreamPlainMarkdown(tail, pendingText);
  }
  function scheduleStreamTailMarkdown() {
    if (streamTailMdRaf) return;
    streamTailMdRaf = requestAnimationFrame(() => {
      flushStreamTailMarkdown();
    });
  }

  function ensureStreamTurn() {
    if (streamArticle) return;
    typingArticle.remove();
    streamArticle = document.createElement('article');
    streamArticle.className = 'turn turn--assistant streaming';
    streamBody = document.createElement('div');
    streamBody.className = 'assistant-flow';
    const meta = createTurnFooter(getTime(), () => extractCopyTextFromFlow(streamBody));
    streamArticle.appendChild(streamBody);
    streamArticle.appendChild(meta);
    messagesEl.appendChild(streamArticle);
    scrollToBottom();
  }

  const chatAbortController = new AbortController();
  activeChatAbortController = chatAbortController;
  try {
    await streamChat(
      apiBase,
      conversationId,
      text,
      (chunk) => {
        pendingText += chunk;
        ensureStreamTurn();
        if (streamBody) {
          getOrCreateTextTail(streamBody);
          scheduleStreamTailMarkdown();
        }
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
              setStreamPlainMarkdown(block, pendingText);
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
          if (streamBody) {
            getOrCreateTextTail(streamBody);
            flushStreamTailMarkdown();
          }
        }
        if (typeof ev.conversation_id === 'string') {
          conversationId = ev.conversation_id;
          saveConversationId(conversationId);
        }
      },
      chatAbortController.signal
    );

    typingArticle.remove();
    const finalTime = getTime();

    if (streamArticle && streamBody) {
      if (streamTailMdRaf) {
        cancelAnimationFrame(streamTailMdRaf);
        streamTailMdRaf = 0;
      }
      flushStreamTailMarkdown();

      if (pendingText.trim()) {
        const tail = streamBody.querySelector('.stream-plain--tail');
        if (tail) {
          setStreamPlainMarkdown(tail, pendingText);
          tail.classList.remove('stream-plain--tail');
        } else {
          const block = document.createElement('div');
          block.className = 'markdown-body stream-plain';
          setStreamPlainMarkdown(block, pendingText);
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
          const t = streamPlainSourceText(el);
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
    if (err instanceof DOMException && err.name === 'AbortError') {
      appendAssistantTurn('*Response stopped by user.*', getTime(), null);
      history.push({
        role: 'assistant',
        time: getTime(),
        segments: [{ type: 'text', text: 'Response stopped by user.' }],
        text: 'Response stopped by user.',
      });
      saveMessages(history);
    } else {
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
  } finally {
    if (activeChatAbortController === chatAbortController) {
      activeChatAbortController = null;
    }
  }

  setSending(false);
}

function setSending(nextSending) {
  isSending = Boolean(nextSending);
  userInput.disabled = isSending;
  updateComposerControls();
}

menuClearBtn?.addEventListener('click', async () => {
  if (!confirm('Delete this chat? Server copy removed if linked.')) return;
  closeTopbarMenu();
  const id = conversationId;
  if (id) {
    try {
      const apiBase = await loadApiBaseValue();
      await deleteConversationOnServer(apiBase, id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      appendSystemNote(`Could not delete conversation on server: ${msg}`);
      return;
    }
  }
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

/**
 * Send: bright “ready” fill when there is text.
 * Mic: separate “voice armed” look only when there is text and capture is idle (recording/transcribe use their own skins).
 */
function syncComposerFilledButtons() {
  const has = Boolean(userInput.value && userInput.value.trim().length > 0);
  sendBtn?.classList.toggle('composer-fab--filled', has);
  if (micBtn) {
    const voiceArmed = has && !isRecording && !isTranscribing && !isSending;
    micBtn.classList.toggle('composer-fab--voice-armed', voiceArmed);
  }
}

let _composerMeasureMirror = null;

function _getComposerMeasureMirror() {
  if (_composerMeasureMirror) return _composerMeasureMirror;
  const ta = document.createElement('textarea');
  ta.setAttribute('readonly', 'readonly');
  ta.setAttribute('tabindex', '-1');
  ta.setAttribute('aria-hidden', 'true');
  ta.style.cssText =
    'position:fixed;left:-99999px;top:0;opacity:0;pointer-events:none;resize:none;overflow:hidden;';
  document.body.appendChild(ta);
  _composerMeasureMirror = ta;
  return ta;
}

function _syncMirrorLayoutFromComposer(mirror) {
  const s = window.getComputedStyle(userInput);
  const w = userInput.getBoundingClientRect().width;
  if (!w || w < 8) return false;
  mirror.style.width = `${w}px`;
  mirror.style.boxSizing = s.boxSizing;
  mirror.style.font = s.font;
  mirror.style.fontSize = s.fontSize;
  mirror.style.fontWeight = s.fontWeight;
  mirror.style.fontFamily = s.fontFamily;
  mirror.style.lineHeight = s.lineHeight;
  mirror.style.padding = `${s.paddingTop} ${s.paddingRight} ${s.paddingBottom} ${s.paddingLeft}`;
  mirror.style.border = s.border;
  mirror.style.letterSpacing = s.letterSpacing;
  mirror.style.whiteSpace = 'pre-wrap';
  mirror.style.wordBreak = s.wordBreak === 'normal' ? 'break-word' : s.wordBreak;
  mirror.style.minHeight = `${COMPOSER_TEXTAREA_MIN_PX}px`;
  return true;
}

/** Native placeholder does not affect textarea scrollHeight; mirror measures wrapped height. */
function measureComposerHeightForPlaceholderText(text) {
  const mirror = _getComposerMeasureMirror();
  if (!_syncMirrorLayoutFromComposer(mirror)) return COMPOSER_TEXTAREA_MIN_PX;
  mirror.value = text && text.length ? text : ' ';
  mirror.style.height = 'auto';
  const raw = mirror.scrollHeight;
  return Math.min(Math.max(raw, COMPOSER_TEXTAREA_MIN_PX), COMPOSER_TEXTAREA_MAX_PX);
}

function autoResize() {
  const hasBody = Boolean(userInput.value && userInput.value.trim());
  let px;
  if (!hasBody) {
    px = measureComposerHeightForPlaceholderText(userInput.placeholder || DEFAULT_PLACEHOLDER_TEXT);
  } else {
    userInput.style.height = 'auto';
    const raw = userInput.scrollHeight;
    px = Math.min(Math.max(raw, COMPOSER_TEXTAREA_MIN_PX), COMPOSER_TEXTAREA_MAX_PX);
  }
  userInput.style.height = `${px}px`;
  syncComposerFilledButtons();
  syncComposerPlaceholderGhost();
}

function canFillFromPlaceholderSuggestion() {
  if (!userInput || userInput.disabled) return false;
  if (userInput.value.trim()) return false;
  const ph = userInput.placeholder;
  if (!ph || ph === DEFAULT_PLACEHOLDER_TEXT) return false;
  if (!activeTypewriterPhraseFull) return false;
  return activeTypewriterPhraseFull.startsWith(ph);
}

function fillInputFromAnimatedPlaceholder() {
  if (!canFillFromPlaceholderSuggestion()) return false;
  const ph = userInput.placeholder;
  const text = activeTypewriterPhraseFull.startsWith(ph) ? activeTypewriterPhraseFull : ph;
  userInput.value = text;
  userInput.placeholder = DEFAULT_PLACEHOLDER_TEXT;
  refreshPlaceholderTypewriterPause();
  autoResize();
  syncComposerFilledButtons();
  return true;
}

function _clearPlaceholderPressTimer() {
  if (_placeholderPressTimer != null) {
    clearTimeout(_placeholderPressTimer);
    _placeholderPressTimer = null;
  }
}

function _detachPlaceholderPressWindowListeners() {
  if (!_placeholderPressTracking) return;
  _placeholderPressTracking = false;
  window.removeEventListener('pointermove', _onPlaceholderPressWindowMove);
  window.removeEventListener('pointerup', _onPlaceholderPressWindowEnd);
  window.removeEventListener('pointercancel', _onPlaceholderPressWindowEnd);
}

function _onPlaceholderPressWindowMove(e) {
  const dx = Math.abs(e.clientX - _placeholderPressDownX);
  const dy = Math.abs(e.clientY - _placeholderPressDownY);
  if (dx + dy > 14) {
    _clearPlaceholderPressTimer();
    _detachPlaceholderPressWindowListeners();
  }
}

function _onPlaceholderPressWindowEnd() {
  _clearPlaceholderPressTimer();
  _detachPlaceholderPressWindowListeners();
}

function _onPlaceholderLongPressTimeout() {
  _placeholderPressTimer = null;
  if (fillInputFromAnimatedPlaceholder()) {
    userInput.focus();
  }
  _detachPlaceholderPressWindowListeners();
}

userInput.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  _clearPlaceholderPressTimer();
  _detachPlaceholderPressWindowListeners();
  if (!canFillFromPlaceholderSuggestion()) return;
  _placeholderPressDownX = e.clientX;
  _placeholderPressDownY = e.clientY;
  _placeholderPressTracking = true;
  window.addEventListener('pointermove', _onPlaceholderPressWindowMove);
  window.addEventListener('pointerup', _onPlaceholderPressWindowEnd);
  window.addEventListener('pointercancel', _onPlaceholderPressWindowEnd);
  _placeholderPressTimer = setTimeout(_onPlaceholderLongPressTimeout, PLACEHOLDER_LONG_PRESS_MS);
});

userInput.addEventListener('dblclick', (e) => {
  if (!canFillFromPlaceholderSuggestion()) return;
  e.preventDefault();
  _clearPlaceholderPressTimer();
  _detachPlaceholderPressWindowListeners();
  if (fillInputFromAnimatedPlaceholder()) {
    userInput.focus();
  }
});

userInput.addEventListener('input', () => {
  autoResize();
  refreshPlaceholderTypewriterPause();
});

userInput.addEventListener('focus', () => {
  refreshPlaceholderTypewriterPause();
  autoResize();
});

userInput.addEventListener('blur', () => {
  refreshPlaceholderTypewriterPause();
  autoResize();
});

userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (isRecording) {
      void finalizeRecordingAndTranscribe(false);
      return;
    }
    if (isSending) {
      abortCurrentChat();
      return;
    }
    if (isTranscribing) {
      cancelTranscription();
      return;
    }
    void sendMessage();
  }
});

sendBtn.addEventListener('click', () => {
  if (isRecording) {
    void finalizeRecordingAndTranscribe(true);
    return;
  }
  if (isTranscribing) {
    cancelTranscription();
    return;
  }
  if (isSending) {
    abortCurrentChat();
    return;
  }
  void sendMessage();
});

micBtn?.addEventListener('click', () => {
  if (isSending) return;
  if (isRecording) {
    void finalizeRecordingAndTranscribe(false);
    return;
  }
  if (isTranscribing) {
    cancelTranscription();
    return;
  }
  void startVoiceRecording();
});

saveApiBtn.addEventListener('click', () => {
  saveApiBase(apiBaseInput.value, (saved) => {
    apiBaseInput.value = saved;
    void loadToolLabelsFromBackend();
    saveApiBtn.textContent = 'Saved';
    closeTopbarMenu();
    setTimeout(() => {
      saveApiBtn.textContent = 'Save';
    }, 1200);
  });
});

refreshPageContextBtn?.addEventListener('click', async () => {
  refreshPageContextBtn.disabled = true;
  const previous = refreshPageContextBtn.textContent;
  refreshPageContextBtn.textContent = 'Refreshing…';
  const snapshot = await requestCurrentPageContext(true);
  renderPageContext(snapshot);
  refreshPageContextBtn.textContent = previous || 'Refresh';
  refreshPageContextBtn.disabled = false;
});

usePageContextToggle?.addEventListener('change', () => {
  saveUsePageContext(usePageContextToggle.checked);
});

menuNewChatBtn?.addEventListener('click', () => {
  closeTopbarMenu();
  startNewChatFromPicker();
});

menuChatsBtn?.addEventListener('click', () => {
  closeTopbarMenu();
  setChatPickerOpen(true);
  void refreshChatPickerList();
});

document.addEventListener('click', (e) => {
  if (!(e.target instanceof Node)) return;
  if (topbarMenu instanceof HTMLDetailsElement && topbarMenu.open && !topbarMenu.contains(e.target)) {
    topbarMenu.open = false;
  }
  chatPickerList?.querySelectorAll('details.chat-picker-row-menu').forEach((d) => {
    if (d instanceof HTMLDetailsElement && d.open && !d.contains(e.target)) {
      d.open = false;
    }
  });
});

chatPickerBackdrop?.addEventListener('click', () => {
  setChatPickerOpen(false);
});

chatPickerClose?.addEventListener('click', () => {
  setChatPickerOpen(false);
});

newChatBtn?.addEventListener('click', () => {
  startNewChatFromPicker();
});

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (chatPicker && !chatPicker.hasAttribute('hidden')) {
    setChatPickerOpen(false);
    e.preventDefault();
    return;
  }
  if (topbarMenu instanceof HTMLDetailsElement && topbarMenu.open) {
    topbarMenu.open = false;
    e.preventDefault();
  }
});

loadApiBase((base) => {
  apiBaseInput.value = base;
});

loadUsePageContext((enabled) => {
  if (usePageContextToggle) usePageContextToggle.checked = enabled;
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

updateComposerControls();
syncComposerFilledButtons();
autoResize();
window.addEventListener('resize', () => autoResize());
void loadToolLabelsFromBackend();

requestCurrentPageContext(false).then((snapshot) => {
  renderPageContext(snapshot);
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === 'PAGE_CONTEXT_UPDATED') {
    renderPageContext(message.payload || null);
  }
});

window.addEventListener('beforeunload', () => {
  placeholderLoopActive = false;
  clearPlaceholderTypewriterTimers();
  _clearPlaceholderPressTimer();
  _detachPlaceholderPressWindowListeners();
  cancelTranscription();
  abortCurrentChat();
  stopMediaStream();
});

void runPlaceholderTypewriterLoop();
