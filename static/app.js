const THEME_STORAGE_KEY = "chatbot-research-theme";

const state = {
  sidebar: window.__INITIAL_SIDEBAR__ || {},
  messages: [],
};

const chatLog = document.querySelector("#chat-log");
const chatForm = document.querySelector("#chat-form");
const messageInput = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-btn");
const clearButton = document.querySelector("#clear-btn");
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

function appendMessage(role, text, options = {}) {
  const node = template.content.firstElementChild.cloneNode(true);
  const bubble = node.querySelector(".bubble");
  const meta = node.querySelector(".meta");
  const sources = node.querySelector(".sources");
  const sourcesSummary = node.querySelector(".sources-summary");
  const sourcesList = node.querySelector(".sources-list");

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
    sourcesSummary.textContent = `แหล่งอ้างอิง (${options.passages.length})`;
    sourcesList.replaceChildren(...options.passages.map(renderSourceCard));
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
  messageInput.disabled = isBusy;
  sendButton.textContent = isBusy ? "Sending..." : "Send";
}

function describeMode(mode) {
  if (mode === "grounded") return "ตอบจากเอกสาร";
  if (mode === "conversation") return "ตอบแบบ AI";
  if (mode === "assistant_fallback") return "โหมด fallback";
  if (mode === "needs_provider") return "ต้องมี API key";
  if (mode === "provider_error") return "provider error";
  if (mode === "no_documents") return "ยังไม่มีเอกสาร";
  return mode || "response";
}

function describeProvider(provider) {
  if (!provider) return "";
  if (provider === "local") return "local";
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

function buildPayload(message, history) {
  return {
    message,
    history,
  };
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) return;

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

clearButton.addEventListener("click", () => {
  state.messages = [];
  chatLog.replaceChildren();
  appendMessage(
    "assistant",
    "สวัสดีครับ ถามเรื่องการประกอบคอมพิวเตอร์ได้เลย ระบบจะค้นหาจากเอกสารวิจัยและอ้างอิงแหล่งที่มาให้",
    { persist: false },
  );
});
