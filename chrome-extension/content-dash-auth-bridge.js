'use strict';

/** Must stay in sync with frontend `notifyChromeExtensionLogout.ts` postMessage payload. */
const MSG_V = 1;
const MSG_SOURCE = 'logistic-copilot-dashboard';
const MSG_ACTION = 'extension-session-clear';

window.addEventListener('message', (event) => {
  if (event.origin !== window.location.origin) return;
  const d = event.data;
  if (!d || typeof d !== 'object') return;
  if (d.source !== MSG_SOURCE || d.action !== MSG_ACTION || d.v !== MSG_V) return;
  chrome.runtime.sendMessage({ type: 'WEB_DASHBOARD_LOGOUT' }, () => {
    void chrome.runtime.lastError;
  });
});
