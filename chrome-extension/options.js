const STORAGE_API_BASE = 'api_base_url';
const STORAGE_FRONTEND_BASE = 'frontend_base_url';
const STORAGE_AUTH_TOKEN = 'auth_token';

const DEFAULT_API_BASE = 'https://api.logisticopilot.com';
const DEFAULT_FRONTEND_BASE = 'https://logisticopilot.com';

const ENV_PRESETS = {
  prod: { api: DEFAULT_API_BASE, frontend: DEFAULT_FRONTEND_BASE },
  local: { api: 'http://localhost:8000', frontend: 'http://localhost:3000' },
};

const optEnvProd = document.getElementById('optEnvProd');
const optEnvLocal = document.getElementById('optEnvLocal');
const optUrlsSummary = document.getElementById('optUrlsSummary');
const optApiBase = document.getElementById('optApiBase');
const optFrontendBase = document.getElementById('optFrontendBase');
const optApplyCustom = document.getElementById('optApplyCustom');
const optionsStatus = document.getElementById('optionsStatus');

/** @param {string} url @param {string} fallback */
function normalizeEnvUrl(url, fallback) {
  const t = String(url || '')
    .trim()
    .replace(/\/+$/, '');
  return t || fallback;
}

function storageGet(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.get(keys, resolve);
  });
}

function storageSet(obj) {
  return new Promise((resolve) => {
    chrome.storage.local.set(obj, resolve);
  });
}

function storageRemove(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.remove(keys, resolve);
  });
}

function setStatus(msg) {
  if (optionsStatus) optionsStatus.textContent = msg || '';
}

function syncSwitcherUI() {
  if (!optEnvProd || !optEnvLocal || !optUrlsSummary || !optApiBase || !optFrontendBase) return;
  const api = normalizeEnvUrl(optApiBase.value, DEFAULT_API_BASE);
  const fe = normalizeEnvUrl(optFrontendBase.value, DEFAULT_FRONTEND_BASE);
  const pa = normalizeEnvUrl(ENV_PRESETS.prod.api, DEFAULT_API_BASE);
  const pf = normalizeEnvUrl(ENV_PRESETS.prod.frontend, DEFAULT_FRONTEND_BASE);
  const la = normalizeEnvUrl(ENV_PRESETS.local.api, ENV_PRESETS.local.api);
  const lf = normalizeEnvUrl(ENV_PRESETS.local.frontend, ENV_PRESETS.local.frontend);
  let active = null;
  if (api === pa && fe === pf) active = 'prod';
  else if (api === la && fe === lf) active = 'local';
  optEnvProd.classList.toggle('options-env-btn--active', active === 'prod');
  optEnvLocal.classList.toggle('options-env-btn--active', active === 'local');
  optUrlsSummary.textContent = `${api} · ${fe}`;
}

async function loadFieldsFromStorage() {
  const r = await storageGet([STORAGE_API_BASE, STORAGE_FRONTEND_BASE]);
  const api = normalizeEnvUrl(r[STORAGE_API_BASE], DEFAULT_API_BASE);
  const fe = normalizeEnvUrl(r[STORAGE_FRONTEND_BASE], DEFAULT_FRONTEND_BASE);
  if (optApiBase) optApiBase.value = api;
  if (optFrontendBase) optFrontendBase.value = fe;
  syncSwitcherUI();
}

async function applyEndpoints(nextApiRaw, nextFeRaw) {
  const r = await storageGet([STORAGE_API_BASE, STORAGE_FRONTEND_BASE]);
  const beforeApi = normalizeEnvUrl(r[STORAGE_API_BASE], DEFAULT_API_BASE);
  const beforeFe = normalizeEnvUrl(r[STORAGE_FRONTEND_BASE], DEFAULT_FRONTEND_BASE);
  const api = normalizeEnvUrl(nextApiRaw, DEFAULT_API_BASE);
  const fe = normalizeEnvUrl(nextFeRaw, DEFAULT_FRONTEND_BASE);

  await storageSet({
    [STORAGE_API_BASE]: api,
    [STORAGE_FRONTEND_BASE]: fe,
  });

  if (optApiBase) optApiBase.value = api;
  if (optFrontendBase) optFrontendBase.value = fe;
  syncSwitcherUI();

  if (beforeApi !== api || beforeFe !== fe) {
    await storageRemove([STORAGE_AUTH_TOKEN]);
    setStatus('Saved. You were signed out because URLs changed. Reload the side panel.');
  } else {
    setStatus('Saved (no URL change).');
  }
}

optEnvProd?.addEventListener('click', () => {
  void applyEndpoints(ENV_PRESETS.prod.api, ENV_PRESETS.prod.frontend);
});

optEnvLocal?.addEventListener('click', () => {
  void applyEndpoints(ENV_PRESETS.local.api, ENV_PRESETS.local.frontend);
});

optApplyCustom?.addEventListener('click', () => {
  void applyEndpoints(optApiBase?.value || '', optFrontendBase?.value || '');
});

optApiBase?.addEventListener('input', () => syncSwitcherUI());
optFrontendBase?.addEventListener('input', () => syncSwitcherUI());

void loadFieldsFromStorage();
