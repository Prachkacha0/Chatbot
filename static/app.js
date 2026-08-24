const STORAGE_KEY = "chatbot-research-settings";
const THEME_STORAGE_KEY = "chatbot-research-theme";

const state = {
  sidebar: window.__INITIAL_SIDEBAR__ || {},
  messages: [],
};

const chatLog = document.querySelector("#chat-log");
const chatForm = document.querySelector("#chat-form");
const messageInput = document.querySelector("#message-input");
const typhoonApiKeyInput = document.querySelector("#typhoon-api-key");
const geminiApiKeyInput = document.querySelector("#gemini-api-key");
const groundedProviderInput = document.querySelector("#grounded-provider");
const conversationProviderInput = document.querySelector("#conversation-provider");
const topKInput = document.querySelector("#top-k");
const temperatureInput = document.querySelector("#temperature");
const sendButton = document.querySelector("#send-btn");
const clearButton = document.querySelector("#clear-btn");
const reloadButton = document.querySelector("#reload-btn");
const template = document.querySelector("#message-template");
const themeToggleButton = document.querySelector("#theme-toggle");
const sidebarToggleButton = document.querySelector("#sidebar-toggle");
const sidebar = document.querySelector(".sidebar");

function systemPrefersDark() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyTheme(theme) {
  const isDark = theme === "dark" || (theme === "system" && systemPrefersDark());
  if (theme === "system") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", theme);
  }
  themeToggleButton.classList.toggle("is-dark", isDark);
}

function initTheme() {
  const saved = localStorage.getItem(THEME_STORAGE_KEY) || "system";
  applyTheme(saved);
}

themeToggleButton.addEventListener("click", () => {
  const current = localStorage.getItem(THEME_STORAGE_KEY) || "system";
  const currentIsDark = current === "dark" || (current === "system" && systemPrefersDark());
  const next = currentIsDark ? "light" : "dark";
  localStorage.setItem(THEME_STORAGE_KEY, next);
  applyTheme(next);
});

initTheme();

sidebarToggleButton.addEventListener("click", () => {
  const isOpen = sidebar.classList.toggle("is-open");
  sidebarToggleButton.setAttribute("aria-expanded", String(isOpen));
});

function restoreSettings() {
  const serverGroundedDefault = state.sidebar.default_grounded_provider || "typhoon";
  const serverConversationDefault = state.sidebar.default_conversation_provider || "typhoon";
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    topKInput.value = String(saved.top_k || 5);
    temperatureInput.value = String(saved.temperature ?? 0.2);
    groundedProviderInput.value =
      saved.grounded_provider && saved.grounded_provider !== "auto"
        ? saved.grounded_provider
        : serverGroundedDefault;
    conversationProviderInput.value =
      saved.conversation_provider && saved.conversation_provider !== "auto"
        ? saved.conversation_provider
        : serverConversationDefault;
  } catch {
    groundedProviderInput.value = serverGroundedDefault;
    conversationProviderInput.value = serverConversationDefault;
  }
}

function persistSettings() {
  const payload = {
    top_k: Number(topKInput.value) || 5,
    temperature: Number(temperatureInput.value) || 0.2,
    grounded_provider: groundedProviderInput.value,
    conversation_provider: conversationProviderInput.value,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

function appendMessage(role, text, options = {}) {
  const node = template.content.firstElementChild.cloneNode(true);
  const bubble = node.querySelector(".bubble");
  const meta = node.querySelector(".meta");
  const sources = node.querySelector(".sources");

  node.classList.add(role);

  if (options.isError) {
    node.classList.add("error-message");
    bubble.innerHTML = `<p>⚠️ ${escapeHtml(text)}</p>`;
  } else if (role === "assistant" && typeof marked !== "undefined") {
    marked.setOptions({ breaks: true, gfm: true });
    const rawHtml = marked.parse(text);
    bubble.innerHTML = typeof DOMPurify !== "undefined"
      ? DOMPurify.sanitize(rawHtml)
      : rawHtml;
  } else {
    bubble.innerHTML = `<p>${escapeHtml(text)}</p>`;
  }

  if (options.meta) {
    meta.textContent = options.meta;
  } else {
    meta.remove();
  }

  if (Array.isArray(options.passages) && options.passages.length > 0) {
    sources.replaceChildren(...options.passages.map(renderSourceCard));
  } else {
    sources.remove();
  }

  chatLog.appendChild(node);
  chatLog.scrollTop = chatLog.scrollHeight;

  if (options.persist !== false && (role === "user" || role === "assistant")) {
    state.messages.push({ role, content: text });
  }

  return node;
}

function showTypingIndicator() {
  const node = template.content.firstElementChild.cloneNode(true);
  const bubble = node.querySelector(".bubble");
  const meta = node.querySelector(".meta");
  const sources = node.querySelector(".sources");

  node.classList.add("assistant", "typing-indicator");
  bubble.innerHTML = `
    <span class="typing-dots">
      <span></span><span></span><span></span>
    </span>
  `;
  meta.remove();
  sources.remove();

  chatLog.appendChild(node);
  chatLog.scrollTop = chatLog.scrollHeight;
  return node;
}

function renderSourceCard(passage) {
  const card = document.createElement("section");
  card.className = "source-card";
  const score = `${Math.round((passage.score || 0) * 100)}%`;
  card.innerHTML = `
    <header>
      <strong>${escapeHtml(passage.source)}</strong>
      <span class="source-score">match ${score}</span>
    </header>
    <p>${escapeHtml(trimSnippet(passage.text))}</p>
  `;
  return card;
}

function trimSnippet(text) {
  const clean = (text || "").trim();
  return clean.length > 420 ? `${clean.slice(0, 420)}...` : clean;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setBusy(isBusy) {
  sendButton.disabled = isBusy;
  reloadButton.disabled = isBusy;
  messageInput.disabled = isBusy;
  sendButton.textContent = isBusy ? "Sending..." : "Send";
}

function describeMode(mode) {
  if (mode === "grounded") {
    return "ตอบจากเอกสาร";
  }
  if (mode === "conversation") {
    return "ตอบแบบ AI";
  }
  if (mode === "assistant_fallback") {
    return "โหมด fallback";
  }
  if (mode === "needs_provider") {
    return "ต้องมี API key";
  }
  if (mode === "provider_error") {
    return "provider error";
  }
  if (mode === "no_documents") {
    return "ยังไม่มีเอกสาร";
  }
  return mode || "response";
}

function describeProvider(provider) {
  if (!provider) {
    return "";
  }
  if (provider === "local") {
    return "local";
  }
  return provider;
}

async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Request failed.");
  }
  return data;
}

function renderSidebar(sidebar) {
  state.sidebar = sidebar;
  document.querySelector("#doc-count").textContent = sidebar.doc_count;
  document.querySelector("#chunk-count").textContent = sidebar.chunk_count;
  document.querySelector("#char-count").textContent = sidebar.char_count;

  const fileList = document.querySelector("#file-list");
  fileList.replaceChildren();

  if (!sidebar.files || sidebar.files.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-note";
    empty.textContent = "ยังไม่มีเอกสารในโฟลเดอร์ data";
    fileList.appendChild(empty);
    return;
  }

  sidebar.files.forEach((file) => {
    const item = document.createElement("article");
    item.className = "file-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(file.source)}</strong>
        <p>${file.chunks} chunks · ${file.chars} chars</p>
      </div>
      <span>${escapeHtml(file.ext)}</span>
    `;
    fileList.appendChild(item);
  });
}

function buildPayload(message, history) {
  return {
    message,
    typhoon_api_key: typhoonApiKeyInput.value.trim() || null,
    gemini_api_key: geminiApiKeyInput.value.trim() || null,
    top_k: Number(topKInput.value) || 5,
    temperature: Number(temperatureInput.value) || 0.2,
    history,
    grounded_provider: groundedProviderInput.value,
    conversation_provider: conversationProviderInput.value,
  };
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) {
    return;
  }

  persistSettings();
  const history = state.messages.slice(-8);
  appendMessage("user", message);
  messageInput.value = "";
  setBusy(true);
  const typingNode = showTypingIndicator();

  try {
    const result = await postJson("/api/chat", buildPayload(message, history));
    const mode = describeMode(result.mode);
    const provider = describeProvider(result.provider_used);
    const meta = provider
      ? `${mode} · ${provider} · ${result.elapsed.toFixed(2)}s`
      : `${mode} · ${result.elapsed.toFixed(2)}s`;
    typingNode.remove();
    appendMessage("assistant", result.answer, {
      meta,
      passages: result.passages,
    });
  } catch (error) {
    typingNode.remove();
    appendMessage("assistant", error.message, { meta: "request failed", isError: true });
  } finally {
    setBusy(false);
    messageInput.focus();
  }
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

reloadButton.addEventListener("click", async () => {
  setBusy(true);
  try {
    const sidebar = await postJson("/api/reload");
    renderSidebar(sidebar);
    appendMessage("assistant", "รีโหลดเอกสารเรียบร้อยแล้ว", {
      meta: "knowledge base refreshed",
      persist: false,
    });
  } catch (error) {
    appendMessage("assistant", error.message, { meta: "reload failed", isError: true });
  } finally {
    setBusy(false);
  }
});

clearButton.addEventListener("click", () => {
  state.messages = [];
  chatLog.replaceChildren();
  appendMessage(
    "assistant",
    "พร้อมใช้งานครับ จะถามคุยทั่วไปก่อน หรือถามจากไฟล์ในโฟลเดอร์ data ก็ได้",
    { persist: false },
  );
});

[
  typhoonApiKeyInput,
  geminiApiKeyInput,
  groundedProviderInput,
  conversationProviderInput,
  topKInput,
  temperatureInput,
].forEach((element) => {
  element.addEventListener("change", persistSettings);
  element.addEventListener("input", persistSettings);
});

restoreSettings();
