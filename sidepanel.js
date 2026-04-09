const messagesEl = document.getElementById('messages');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const clearBtn = document.getElementById('clearBtn');
const pageBtn = document.getElementById('pageBtn');

// ---- Storage helpers ----
const STORAGE_KEY = 'assistant_messages';

function saveMessages(msgs) {
  chrome.storage.local.set({ [STORAGE_KEY]: msgs });
}

function loadMessages(callback) {
  chrome.storage.local.get([STORAGE_KEY], (result) => {
    callback(result[STORAGE_KEY] || []);
  });
}

// ---- UI helpers ----
function getTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function appendMessage(role, text, time) {
  const wrapper = document.createElement('div');
  wrapper.className = `message ${role}`;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;

  const timeEl = document.createElement('span');
  timeEl.className = 'time';
  timeEl.textContent = time || getTime();

  wrapper.appendChild(bubble);
  wrapper.appendChild(timeEl);
  messagesEl.appendChild(wrapper);
  scrollToBottom();
  return wrapper;
}

function showTyping() {
  const wrapper = document.createElement('div');
  wrapper.className = 'message assistant typing';
  wrapper.innerHTML = `
    <div class="bubble">
      <span class="dot"></span>
      <span class="dot"></span>
      <span class="dot"></span>
    </div>`;
  messagesEl.appendChild(wrapper);
  scrollToBottom();
  return wrapper;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ---- Mock AI response (replace with real API later) ----
async function getAssistantReply(userText) {
  // Simulate network delay
  await new Promise(r => setTimeout(r, 800 + Math.random() * 600));

  const replies = [
    `Got it! You said: "${userText}". I'm a demo assistant — connect me to an AI API to get real answers.`,
    `Interesting question! This is a placeholder response. You can wire this up to OpenAI, Gemini, or any LLM API.`,
    `I understand. To make me smarter, replace the \`getAssistantReply\` function in sidepanel.js with a real API call.`,
    `Thanks for testing! The UI is working. Next step: connect to an LLM backend of your choice.`,
  ];

  return replies[Math.floor(Math.random() * replies.length)];
}

// ---- Send message ----
let history = []; // { role, text, time }

async function sendMessage() {
  const text = userInput.value.trim();
  if (!text) return;

  userInput.value = '';
  autoResize();
  setSending(true);

  const userTime = getTime();
  appendMessage('user', text, userTime);
  history.push({ role: 'user', text, time: userTime });

  const typingEl = showTyping();

  try {
    const reply = await getAssistantReply(text);
    typingEl.remove();
    const assistantTime = getTime();
    appendMessage('assistant', reply, assistantTime);
    history.push({ role: 'assistant', text: reply, time: assistantTime });
    saveMessages(history);
  } catch (err) {
    typingEl.remove();
    appendMessage('assistant', 'Something went wrong. Please try again.', getTime());
  }

  setSending(false);
}

function setSending(isSending) {
  sendBtn.disabled = isSending;
  userInput.disabled = isSending;
}

// ---- Read page text ----
pageBtn.addEventListener('click', async () => {
  pageBtn.disabled = true;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      appendMessage('assistant', 'Could not access the active tab.');
      return;
    }
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({
        title: document.title,
        url: location.href,
        text: document.body.innerText.replace(/\s+/g, ' ').trim().slice(0, 500)
      })
    });
    const { title, url, text } = results[0].result;
    const msg = `📄 Page: ${title}\n🔗 ${url}\n\nFirst 500 chars:\n${text}`;
    appendMessage('assistant', msg);
  } catch (err) {
    appendMessage('assistant', `Error reading page: ${err.message}`);
  } finally {
    pageBtn.disabled = false;
  }
});

// ---- Clear chat ----
clearBtn.addEventListener('click', () => {
  if (!confirm('Clear conversation history?')) return;
  history = [];
  saveMessages([]);
  messagesEl.innerHTML = '';
  appendMessage('assistant', 'Chat cleared. How can I help you?');
});

// ---- Auto-resize textarea ----
function autoResize() {
  userInput.style.height = 'auto';
  userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
}

userInput.addEventListener('input', autoResize);

// ---- Send on Enter (Shift+Enter = newline) ----
userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener('click', sendMessage);

// ---- Restore history on load ----
loadMessages((saved) => {
  if (saved.length === 0) return;
  // Clear default welcome message
  messagesEl.innerHTML = '';
  history = saved;
  saved.forEach(({ role, text, time }) => appendMessage(role, text, time));
});
