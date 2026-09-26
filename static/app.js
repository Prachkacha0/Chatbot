const THEME_STORAGE_KEY = "polaris-theme";
const SIDEBAR_STORAGE_KEY = "polaris-sidebar-collapsed";
const WELCOME_MESSAGE =
  "สวัสดีครับ ผมคือ **Polaris** ถามเรื่องพื้นฐานคอมพิวเตอร์ได้เลย ผมจะค้นหาจากตำราภาษาไทย 8 บท แล้วตอบพร้อมอ้างอิงเลขหน้าและรูปประกอบ\n\nเลือกบทจากแถบข้างเพื่อดูคำถามตัวอย่างได้ครับ";

const state = {
  messages: [],
};

const chatLog = document.querySelector("#chat-log");
const chatForm = document.querySelector("#chat-form");
const messageInput = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-btn");
const clearButton = document.querySelector("#clear-btn");
const template = document.querySelector("#message-template");
const themeToggleButton = document.querySelector("#theme-toggle");
const imageLightbox = document.querySelector("#image-lightbox");
const imageLightboxImg = imageLightbox.querySelector(".image-lightbox-img");
const imageLightboxCaption = imageLightbox.querySelector(".image-lightbox-caption");
const imageLightboxClose = imageLightbox.querySelector(".image-lightbox-close");
const app = document.querySelector(".app");
const sidebarToggleButton = document.querySelector("#sidebar-toggle");
const sidebarBackdrop = document.querySelector("#sidebar-backdrop");
const chatMenuButton = document.querySelector("#chat-menu-btn");
const chatMenu = document.querySelector("#chat-menu");
const mobileQuery = window.matchMedia("(max-width: 1024px)");

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

function isSidebarVisible() {
  return mobileQuery.matches
    ? app.classList.contains("sidebar-open")
    : !app.classList.contains("sidebar-collapsed");
}

function syncSidebarState() {
  sidebarBackdrop.hidden = !(mobileQuery.matches && app.classList.contains("sidebar-open"));
  sidebarToggleButton.setAttribute("aria-expanded", String(isSidebarVisible()));
}

function closeMobileSidebar() {
  app.classList.remove("sidebar-open");
  syncSidebarState();
}

sidebarToggleButton.addEventListener("click", () => {
  if (mobileQuery.matches) {
    app.classList.toggle("sidebar-open");
  } else {
    const collapsed = app.classList.toggle("sidebar-collapsed");
    localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "1" : "0");
  }
  syncSidebarState();
});

sidebarBackdrop.addEventListener("click", closeMobileSidebar);
mobileQuery.addEventListener("change", () => {
  app.classList.remove("sidebar-open");
  syncSidebarState();
});

app.classList.toggle("sidebar-collapsed", localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1");
syncSidebarState();

function setChatMenuOpen(open) {
  chatMenu.hidden = !open;
  chatMenuButton.setAttribute("aria-expanded", String(open));
}

chatMenuButton.addEventListener("click", (event) => {
  event.stopPropagation();
  setChatMenuOpen(chatMenu.hidden);
});

document.addEventListener("click", (event) => {
  if (!chatMenu.hidden && !chatMenu.contains(event.target)) setChatMenuOpen(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!chatMenu.hidden) {
    setChatMenuOpen(false);
    chatMenuButton.focus();
  }
  if (app.classList.contains("sidebar-open")) closeMobileSidebar();
});

function autoGrowInput() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${messageInput.scrollHeight}px`;
}

messageInput.addEventListener("input", autoGrowInput);

document.querySelectorAll(".chapter-item").forEach((button) => {
  button.addEventListener("click", () => {
    messageInput.value = button.dataset.question;
    autoGrowInput();
    closeMobileSidebar();
    messageInput.focus();
  });
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

  const imagesContainer = node.querySelector(".answer-images");
  if (Array.isArray(options.images) && options.images.length > 0) {
    imagesContainer.replaceChildren(...options.images.map(renderImageCard));
  } else {
    imagesContainer.remove();
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
  const images = node.querySelector(".answer-images");

  node.classList.add("assistant", "typing-indicator");
  bubble.innerHTML = `
    <span class="typing-dots">
      <span></span><span></span><span></span>
    </span>
  `;
  meta.remove();
  sources.remove();
  images.remove();

  chatLog.appendChild(node);
  chatLog.scrollTop = chatLog.scrollHeight;
  return node;
}

function renderImageCard(image) {
  const card = document.createElement("figure");
  card.className = "answer-image-card";
  const src = `/${image.file}`.replace(/^\/+/, "/");
  card.innerHTML = `
    <img src="${escapeHtml(src)}" alt="${escapeHtml(image.caption || "")}" loading="lazy" />
    <figcaption>${escapeHtml(image.caption || "")}</figcaption>
  `;
  card.querySelector("img").addEventListener("click", () => openImageLightbox(src, image.caption || ""));
  return card;
}

function openImageLightbox(src, caption) {
  imageLightboxImg.src = src;
  imageLightboxImg.alt = caption;
  imageLightboxCaption.textContent = caption;
  imageLightbox.hidden = false;
}

function closeImageLightbox() {
  imageLightbox.hidden = true;
  imageLightboxImg.src = "";
}

imageLightboxClose.addEventListener("click", closeImageLightbox);
imageLightbox.addEventListener("click", (event) => {
  if (event.target === imageLightbox) closeImageLightbox();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !imageLightbox.hidden) closeImageLightbox();
});

function renderSourceCard(passage) {
  const card = document.createElement("section");
  card.className = "source-card";
  const score = `${Math.round((passage.score || 0) * 100)}%`;
  card.innerHTML = `
    <header>
      <strong>${escapeHtml(passage.page || passage.source)}</strong>
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
  sendButton.setAttribute("aria-label", isBusy ? "กำลังส่ง" : "ส่ง");
}

function describeMode(mode) {
  if (mode === "exact_match") return "ตอบตรงจากชุดข้อมูล";
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
  autoGrowInput();
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
      images: result.images,
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

function showWelcome() {
  state.messages = [];
  chatLog.replaceChildren();
  appendMessage("assistant", WELCOME_MESSAGE, { persist: false });
}

clearButton.addEventListener("click", () => {
  setChatMenuOpen(false);
  showWelcome();
  messageInput.focus();
});

showWelcome();
