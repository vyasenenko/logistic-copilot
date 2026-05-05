const STORAGE_CURRENT_PAGE_CONTEXT = 'current_page_context';
const STORAGE_AUTH_TOKEN = 'auth_token';

async function storePageContext(snapshot) {
  const payload = {
    ...snapshot,
    captured_at: snapshot?.captured_at || new Date().toISOString(),
  };
  await chrome.storage.local.set({ [STORAGE_CURRENT_PAGE_CONTEXT]: payload });
  try {
    await chrome.runtime.sendMessage({ type: 'PAGE_CONTEXT_UPDATED', payload });
  } catch {
    // sidepanel may not be open
  }
  return payload;
}

function summarizeVisibleText(raw) {
  const text = String(raw || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > 6000 ? `${text.slice(0, 6000).trimEnd()}…` : text;
}

function trimList(values, limit = 12, itemLimit = 120) {
  const seen = new Set();
  const out = [];
  for (const value of values || []) {
    const text = String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim().slice(0, itemLimit);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
    if (out.length >= limit) break;
  }
  return out;
}

function derivePageTypeHint(snapshot) {
  if (snapshot.selection_text) return 'selected_text_focus';
  if ((snapshot.action_labels || []).length >= 4) return 'interactive_app';
  if ((snapshot.headings || []).length >= 5) return 'content_heavy';
  return null;
}

async function capturePageContextForTab(tabId) {
  if (!tabId) {
    return storePageContext({
      available: false,
      unavailable_reason: 'No active tab available.',
    });
  }
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const clean = (value, limit = 200) =>
          String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim().slice(0, limit);

        const textFrom = (selector) =>
          Array.from(document.querySelectorAll(selector || ''))
            .map((el) => clean(el.innerText || el.textContent || '', 180))
            .filter(Boolean);

        const actionLabels = [
          ...Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]')).map(
            (el) => clean(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('value') || '', 120)
          ),
          ...Array.from(document.querySelectorAll('label')).map((el) => clean(el.innerText || el.textContent || '', 120)),
        ].filter(Boolean);

        const metaDescription =
          document.querySelector('meta[name="description"]')?.getAttribute('content') ||
          document.querySelector('meta[property="og:description"]')?.getAttribute('content') ||
          '';

        const selection = window.getSelection ? clean(window.getSelection().toString(), 1200) : '';
        const bodyText = clean(document.body?.innerText || '', 7000);

        return {
          available: true,
          url: location.href,
          title: document.title || '',
          origin: location.origin || '',
          captured_at: new Date().toISOString(),
          selection_text: selection,
          visible_text_excerpt: bodyText,
          headings: textFrom('h1, h2, h3, h4').slice(0, 12),
          meta_description: clean(metaDescription, 500),
          action_labels: Array.from(new Set(actionLabels)).slice(0, 24),
        };
      },
    });
    const raw = results?.[0]?.result || {};
    const snapshot = {
      available: raw.available !== false,
      url: raw.url || '',
      title: raw.title || '',
      origin: raw.origin || '',
      captured_at: raw.captured_at || new Date().toISOString(),
      selection_text: String(raw.selection_text || '').slice(0, 1200),
      visible_text_excerpt: summarizeVisibleText(raw.visible_text_excerpt || ''),
      headings: trimList(raw.headings, 12, 180),
      meta_description: String(raw.meta_description || '').slice(0, 500),
      action_labels: trimList(raw.action_labels, 24, 120),
      page_type_hint: derivePageTypeHint(raw),
      unavailable_reason: null,
    };
    return storePageContext(snapshot);
  } catch (error) {
    return storePageContext({
      available: false,
      url: '',
      title: '',
      origin: '',
      captured_at: new Date().toISOString(),
      selection_text: '',
      visible_text_excerpt: '',
      headings: [],
      meta_description: '',
      action_labels: [],
      page_type_hint: null,
      unavailable_reason: error instanceof Error ? error.message : String(error),
    });
  }
}

async function captureActiveTabPageContext() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return capturePageContextForTab(tab?.id);
}

function buildDashboardQuoteUrl(base, token) {
  const normalized = String(base || '').trim().replace(/\/$/, '');
  const safeBase = normalized || 'https://logisticopilot.com';
  return `${safeBase}/?quote=${encodeURIComponent(String(token || '').toUpperCase())}`;
}

function isDashboardTabUrl(tabUrl, frontendBase) {
  const normalizedBase = String(frontendBase || '').trim().replace(/\/$/, '');
  if (!tabUrl || !normalizedBase) return false;
  return tabUrl === normalizedBase || tabUrl.startsWith(`${normalizedBase}/`) || tabUrl.startsWith(`${normalizedBase}?`);
}

async function openDashboardQuoteInExistingTab(tabId, destination) {
  const target = new URL(destination);
  const nextPath = `${target.pathname}${target.search}${target.hash}`;
  await chrome.scripting.executeScript({
    target: { tabId },
    func: (path) => {
      window.history.pushState({}, '', path);
      window.dispatchEvent(new PopStateEvent('popstate', { state: {} }));
    },
    args: [nextPath],
  });
  await chrome.tabs.update(tabId, { active: true });
}

// Open side panel when extension icon is clicked
chrome.action.onClicked.addListener(async (tab) => {
  await chrome.sidePanel.open({ tabId: tab.id });
  await capturePageContextForTab(tab.id);
});

// Enable side panel for all tabs by default
chrome.runtime.onInstalled.addListener(async () => {
  await chrome.sidePanel.setOptions({
    enabled: true,
  });
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  await capturePageContextForTab(tabId);
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status === 'complete') {
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    if (!tab?.active) return;
    await capturePageContextForTab(tabId);
  }
});

async function clearExtensionAuthToken() {
  await chrome.storage.local.remove([STORAGE_AUTH_TOKEN]);
}

chrome.runtime.onMessageExternal.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'EXTENSION_SESSION_LOGOUT') return false;
  (async () => {
    try {
      await clearExtensionAuthToken();
      sendResponse({ ok: true });
    } catch (error) {
      sendResponse({
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  })();
  return true;
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === 'WEB_DASHBOARD_LOGOUT') {
    (async () => {
      try {
        await clearExtensionAuthToken();
        sendResponse({ ok: true });
      } catch (error) {
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    })();
    return true;
  }
  if (message?.type === 'CAPTURE_CURRENT_PAGE') {
    captureActiveTabPageContext()
      .then((payload) => sendResponse({ ok: true, payload }))
      .catch((error) => sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) }));
    return true;
  }
  if (message?.type === 'GET_CURRENT_PAGE_CONTEXT') {
    chrome.storage.local.get([STORAGE_CURRENT_PAGE_CONTEXT], (result) => {
      sendResponse({ ok: true, payload: result[STORAGE_CURRENT_PAGE_CONTEXT] || null });
    });
    return true;
  }
  if (message?.type === 'OPEN_DASHBOARD_QUOTE') {
    const token = typeof message?.token === 'string' ? message.token.trim().toUpperCase() : '';
    const frontendBase = typeof message?.frontendBase === 'string' ? message.frontendBase.trim() : '';
    if (!/^Q-[A-Z0-9]{6,}$/.test(token)) {
      sendResponse({ ok: false, error: 'Invalid quote token.' });
      return false;
    }
    const destination = buildDashboardQuoteUrl(frontendBase, token);
    (async () => {
      try {
        const existing = await chrome.tabs.query({ url: destination });
        const existingTab = existing.find((t) => typeof t.id === 'number');
        if (existingTab?.id) {
          await chrome.tabs.update(existingTab.id, { active: true });
          if (typeof existingTab.windowId === 'number') {
            await chrome.windows.update(existingTab.windowId, { focused: true });
          }
          sendResponse({ ok: true, mode: 'focused_existing_tab' });
          return;
        }
        const allTabs = await chrome.tabs.query({});
        const dashboardTab =
          allTabs.find((tab) => tab.active && isDashboardTabUrl(tab.url || '', frontendBase)) ||
          allTabs.find((tab) => isDashboardTabUrl(tab.url || '', frontendBase));
        if (dashboardTab?.id) {
          await openDashboardQuoteInExistingTab(dashboardTab.id, destination);
          if (typeof dashboardTab.windowId === 'number') {
            await chrome.windows.update(dashboardTab.windowId, { focused: true });
          }
          sendResponse({ ok: true, mode: 'updated_existing_dashboard_without_reload' });
          return;
        }
        await chrome.tabs.create({ url: destination, active: true });
        sendResponse({ ok: true, mode: 'opened_new_tab' });
      } catch (error) {
        sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) });
      }
    })();
    return true;
  }
  return false;
});
