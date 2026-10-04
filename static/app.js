const THEME_STORAGE_KEY = "polaris-theme";
const SIDEBAR_STORAGE_KEY = "polaris-sidebar-collapsed";
const CHATS_STORAGE_KEY = "polaris-chats";
const ACTIVE_CHAT_STORAGE_KEY = "polaris-active-chat";
const MAX_CHATS = 20;
const HISTORY_TURNS_SENT = 8;
const NEW_CHAT_TITLE = "แชทใหม่";
const WELCOME_MESSAGE =
  "สวัสดีครับ ผมคือ **Polaris** ถามเรื่องพื้นฐานคอมพิวเตอร์ได้เลย ผมจะค้นหาจากตำราภาษาไทย 8 บท แล้วตอบพร้อมอ้างอิงเลขหน้าและรูปประกอบ\n\nกดปุ่มรูปหนังสือ 📖 ในช่องพิมพ์เพื่อดูหัวข้อในตำราได้ครับ";

const chatLog = document.querySelector("#chat-log");
const chatForm = document.querySelector("#chat-form");
const messageInput = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-btn");
const template = document.querySelector("#message-template");
const themeToggleButton = document.querySelector("#theme-toggle");
const imageLightbox = document.querySelector("#image-lightbox");
const imageLightboxImg = imageLightbox.querySelector(".image-lightbox-img");
const imageLightboxCaption = imageLightbox.querySelector(".image-lightbox-caption");
const imageLightboxClose = imageLightbox.querySelector(".image-lightbox-close");
const app = document.querySelector(".app");
const sidebarToggleButton = document.querySelector("#sidebar-toggle");
const sidebarBackdrop = document.querySelector("#sidebar-backdrop");
const chatTitle = document.querySelector("#chat-title");
const chatHistoryNav = document.querySelector("#chat-history");
const newChatButtons = [
  document.querySelector("#new-chat-btn"),
  document.querySelector("#topbar-new-chat"),
];
const chapterButton = document.querySelector("#chapter-btn");
const chapterPopover = document.querySelector("#chapter-popover");
const mobileQuery = window.matchMedia("(max-width: 1024px)");

function readStorage(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key, value) {
  try {
    if (value === null) {
      localStorage.removeItem(key);
    } else {
      localStorage.setItem(key, value);
    }
    return true;
  } catch {
    return false;
  }
}

/* ---------- Theme ---------- */

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

themeToggleButton.addEventListener("click", () => {
  const current = readStorage(THEME_STORAGE_KEY) || "system";
  const currentIsDark = current === "dark" || (current === "system" && systemPrefersDark());
  const next = currentIsDark ? "light" : "dark";
  writeStorage(THEME_STORAGE_KEY, next);
  applyTheme(next);
});

applyTheme(readStorage(THEME_STORAGE_KEY) || "system");

/* ---------- Sidebar ---------- */

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
    writeStorage(SIDEBAR_STORAGE_KEY, collapsed ? "1" : "0");
  }
  syncSidebarState();
});

sidebarBackdrop.addEventListener("click", closeMobileSidebar);
mobileQuery.addEventListener("change", () => {
  app.classList.remove("sidebar-open");
  syncSidebarState();
});

app.classList.toggle("sidebar-collapsed", readStorage(SIDEBAR_STORAGE_KEY) === "1");
syncSidebarState();

/* ---------- Chapter popup ---------- */

function setChapterPopoverOpen(open) {
  chapterPopover.hidden = !open;
  chapterButton.setAttribute("aria-expanded", String(open));
}

chapterButton.addEventListener("click", (event) => {
  event.stopPropagation();
  setChapterPopoverOpen(chapterPopover.hidden);
});

document.addEventListener("click", (event) => {
  if (!chapterPopover.hidden && !chapterPopover.contains(event.target)) setChapterPopoverOpen(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!imageLightbox.hidden) {
    closeImageLightbox();
    return;
  }
  if (!chapterPopover.hidden) {
    setChapterPopoverOpen(false);
    chapterButton.focus();
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
    setChapterPopoverOpen(false);
    messageInput.focus();
  });
});

/* ---------- Chat storage ---------- */

const state = {
  chats: loadChats(),
  activeId: readStorage(ACTIVE_CHAT_STORAGE_KEY),
  busy: false,
};

function loadChats() {
  try {
    const parsed = JSON.parse(readStorage(CHATS_STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (chat) => chat && typeof chat.id === "string" && Array.isArray(chat.messages),
    );
  } catch {
    return [];
  }
}

function persistChats() {
  state.chats.sort((a, b) => b.updatedAt - a.updatedAt);
  state.chats = state.chats.slice(0, MAX_CHATS);
  // If the browser's storage quota is full, drop the oldest chats until it fits.
  while (!writeStorage(CHATS_STORAGE_KEY, JSON.stringify(state.chats)) && state.chats.length > 1) {
    state.chats.pop();
  }
  writeStorage(ACTIVE_CHAT_STORAGE_KEY, state.activeId);
}

function findChat(id) {
  return state.chats.find((chat) => chat.id === id) || null;
}

function newChatId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function makeTitle(message) {
  const clean = message.replace(/\s+/g, " ").trim();
  return clean.length > 40 ? `${clean.slice(0, 40)}…` : clean;
}

function storablePassages(passages) {
  if (!Array.isArray(passages)) return [];
  return passages.map((passage) => ({
    page: passage.page,
    source: passage.source,
    score: passage.score,
    text: trimSnippet(passage.text),
  }));
}

/* ---------- Chat list ---------- */

function dayGroupLabel(timestamp) {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const dayMs = 24 * 60 * 60 * 1000;
  if (timestamp >= startOfToday.getTime()) return "วันนี้";
  if (timestamp >= startOfToday.getTime() - dayMs) return "เมื่อวาน";
  if (timestamp >= startOfToday.getTime() - 7 * dayMs) return "7 วันที่ผ่านมา";
  return "ก่อนหน้านั้น";
}

function renderChatList() {
  chatHistoryNav.replaceChildren();

  if (state.chats.length === 0) {
    const empty = document.createElement("p");
    empty.className = "chat-history-empty";
    empty.textContent = "ยังไม่มีประวัติแชท";
    chatHistoryNav.appendChild(empty);
    return;
  }

  let currentGroup = "";
  state.chats.forEach((chat) => {
    const group = dayGroupLabel(chat.updatedAt);
    if (group !== currentGroup) {
      currentGroup = group;
      const label = document.createElement("p");
      label.className = "chat-history-group";
      label.textContent = group;
      chatHistoryNav.appendChild(label);
    }

    const item = document.createElement("div");
    item.className = "chat-history-item";
    item.classList.toggle("is-active", chat.id === state.activeId);

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "chat-history-open";
    openButton.textContent = chat.title;
    openButton.title = chat.title;
    if (chat.id === state.activeId) openButton.setAttribute("aria-current", "true");
    openButton.addEventListener("click", () => openChat(chat.id));

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "chat-history-delete";
    deleteButton.setAttribute("aria-label", `ลบแชท ${chat.title}`);
    deleteButton.title = "ลบแชท";
    deleteButton.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>';
    deleteButton.addEventListener("click", () => deleteChat(chat.id));

    item.append(openButton, deleteButton);
    chatHistoryNav.appendChild(item);
  });
}

/* ---------- Chat switching ---------- */

function renderActiveChat() {
  const chat = findChat(state.activeId);
  chatLog.replaceChildren();
  chatTitle.textContent = chat ? chat.title : NEW_CHAT_TITLE;

  if (!chat) {
    appendMessage("assistant", WELCOME_MESSAGE);
    return;
  }
  chat.messages.forEach((message) => {
    appendMessage(message.role, message.content, {
      meta: message.meta,
      passages: message.passages,
      images: message.images,
      webSources: message.webSources,
    });
  });
}

function afterChatSwitch() {
  setChapterPopoverOpen(false);
  closeMobileSidebar();
  renderActiveChat();
  renderChatList();
  messageInput.focus();
}

function startNewChat() {
  state.activeId = null;
  writeStorage(ACTIVE_CHAT_STORAGE_KEY, null);
  afterChatSwitch();
}

function openChat(id) {
  if (!findChat(id)) return;
  state.activeId = id;
  writeStorage(ACTIVE_CHAT_STORAGE_KEY, id);
  afterChatSwitch();
}

function deleteChat(id) {
  const chat = findChat(id);
  if (!chat) return;
  if (!window.confirm(`ลบแชท "${chat.title}" ใช่ไหม? ลบแล้วกู้คืนไม่ได้`)) return;
  state.chats = state.chats.filter((item) => item.id !== id);
  if (state.activeId === id) state.activeId = null;
  persistChats();
  afterChatSwitch();
}

newChatButtons.forEach((button) => button.addEventListener("click", startNewChat));

/* ---------- Message rendering ---------- */

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
  } else if (role === "assistant" && typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
    // Markdown only when the sanitizer also loaded: answers can quote web
    // content, so unsanitized HTML must never reach innerHTML.
    marked.setOptions({ breaks: true, gfm: true });
    bubble.innerHTML = DOMPurify.sanitize(marked.parse(text));
  } else {
    bubble.innerHTML = `<p>${escapeHtml(text)}</p>`;
  }

  if (options.meta) {
    meta.textContent = options.meta;
  } else {
    meta.remove();
  }

  const webSources = Array.isArray(options.webSources)
    ? options.webSources.filter((source) => /^https:\/\//.test(source.url || ""))
    : [];
  if (Array.isArray(options.passages) && options.passages.length > 0) {
    sourcesSummary.textContent = `แหล่งอ้างอิง (${options.passages.length})`;
    sourcesList.replaceChildren(...options.passages.map(renderSourceCard));
  } else if (webSources.length > 0) {
    sourcesSummary.textContent = `แหล่งข้อมูลจากเว็บ (${webSources.length})`;
    sourcesList.replaceChildren(...webSources.map(renderWebSourceCard));
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

function renderWebSourceCard(source) {
  const card = document.createElement("section");
  card.className = "source-card web-source-card";
  const link = document.createElement("a");
  link.href = source.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = source.title || source.url;
  const host = document.createElement("span");
  host.className = "source-score";
  try {
    host.textContent = new URL(source.url).hostname;
  } catch {
    host.textContent = "";
  }
  card.append(link, host);
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

/* ---------- Sending ---------- */

function setBusy(isBusy) {
  state.busy = isBusy;
  sendButton.disabled = isBusy;
  messageInput.disabled = isBusy;
  sendButton.setAttribute("aria-label", isBusy ? "กำลังส่ง" : "ส่ง");
}

function describeMode(mode) {
  if (mode === "exact_match") return "ตอบตรงจากชุดข้อมูล";
  if (mode === "grounded") return "ตอบจากเอกสาร";
  if (mode === "conversation") return "ตอบแบบ AI";
  if (mode === "web_search") return "ค้นจากเว็บ";
  if (mode === "assistant_fallback") return "โหมด fallback";
  if (mode === "needs_provider") return "ต้องมี API key";
  if (mode === "provider_error") return "provider error";
  if (mode === "no_documents") return "ยังไม่มีเอกสาร";
  return mode || "response";
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

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message || state.busy) return;

  let chat = findChat(state.activeId);
  if (!chat) {
    chat = { id: newChatId(), title: makeTitle(message), updatedAt: Date.now(), messages: [] };
    state.chats.unshift(chat);
    state.activeId = chat.id;
    chatLog.replaceChildren();
    chatTitle.textContent = chat.title;
  }
  const chatId = chat.id;
  const history = chat.messages
    .slice(-HISTORY_TURNS_SENT)
    .map(({ role, content }) => ({ role, content }));

  chat.messages.push({ role: "user", content: message });
  chat.updatedAt = Date.now();
  persistChats();
  renderChatList();

  appendMessage("user", message);
  messageInput.value = "";
  autoGrowInput();
  setChapterPopoverOpen(false);
  setBusy(true);
  const typingNode = showTypingIndicator();

  try {
    const result = await postJson("/api/chat", { message, history });
    const provider = result.provider_used || "";
    const modeLabel = describeMode(result.mode);
    const meta = provider
      ? `${modeLabel} · ${provider} · ${result.elapsed.toFixed(2)}s`
      : `${modeLabel} · ${result.elapsed.toFixed(2)}s`;
    const reply = {
      role: "assistant",
      content: result.answer,
      meta,
      passages: storablePassages(result.passages),
      images: Array.isArray(result.images) ? result.images : [],
      webSources: Array.isArray(result.web_sources) ? result.web_sources : [],
    };

    // The chat may have been deleted while waiting for the answer.
    const target = findChat(chatId);
    if (target) {
      target.messages.push(reply);
      target.updatedAt = Date.now();
      persistChats();
      renderChatList();
    }
    typingNode.remove();
    if (state.activeId === chatId) {
      appendMessage("assistant", reply.content, reply);
    }
  } catch (error) {
    typingNode.remove();
    if (state.activeId === chatId) {
      appendMessage("assistant", error.message, { meta: "request failed", isError: true });
    }
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

/* ---------- Start ---------- */

if (state.activeId && !findChat(state.activeId)) state.activeId = null;
renderActiveChat();
renderChatList();
