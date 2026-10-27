/* Smart AI Chatbot — front-end logic (vanilla JavaScript, no build step).
 *
 * Safety notes:
 *  - User text is inserted with textContent (never as HTML).
 *  - Assistant Markdown is converted by `marked`, then cleaned by DOMPurify
 *    BEFORE being inserted as HTML.
 *  - Nothing is kept in localStorage/sessionStorage. The open conversation is
 *    remembered through the URL hash (#c=<id>); theme is saved on the server.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const dom = {
    sidebar: $("sidebar"), scrim: $("scrim"), menuBtn: $("menuBtn"),
    newChatBtn: $("newChatBtn"), searchInput: $("searchInput"),
    list: $("conversationList"), listEmpty: $("listEmpty"),
    settingsBtn: $("settingsBtn"), themeBtn: $("themeBtn"),
    chatTitle: $("chatTitle"), modelChip: $("modelChip"),
    scroll: $("scroll"), thread: $("thread"), welcome: $("welcome"), configNotice: $("configNotice"),
    form: $("composerForm"), input: $("messageInput"), counter: $("counter"),
    sendBtn: $("sendBtn"), stopBtn: $("stopBtn"),
    errorBanner: $("errorBanner"), errorText: $("errorText"), retryBtn: $("retryBtn"), dismissErrorBtn: $("dismissErrorBtn"),
    liveStatus: $("liveStatus"), toast: $("toast"),
    settingsDialog: $("settingsDialog"), themeSelect: $("themeSelect"), styleSelect: $("styleSelect"), aiInfo: $("aiInfo"),
    renameDialog: $("renameDialog"), renameForm: $("renameForm"), renameInput: $("renameInput"),
    deleteDialog: $("deleteDialog"), deleteText: $("deleteText"), confirmDeleteBtn: $("confirmDeleteBtn"),
  };

  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const MAX_CHARS = Number(document.querySelector('meta[name="max-message-chars"]').content) || 4000;
  const DEFAULT_TITLE = "New chat";

  const state = {
    conversations: [], activeId: null, busy: false, controller: null,
    settings: { theme: "dark", response_style: "balanced" }, ai: { configured: false, model: null },
    pendingRename: null, pendingDelete: null, stickToBottom: true, searchTimer: null,
  };

  // ---------- Small helpers ----------
  const SVG = (paths) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
  const ICONS = {
    copy: SVG('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>'),
    check: SVG('<path d="M5 12l5 5 9-10"/>'),
    refresh: SVG('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>'),
    edit: SVG('<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>'),
    trash: SVG('<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>'),
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function iconButton(className, iconName, label, text) {
    const btn = el("button", className);
    btn.type = "button";
    btn.setAttribute("aria-label", label);
    btn.title = label;
    btn.insertAdjacentHTML("afterbegin", ICONS[iconName]); // constant, trusted markup
    if (text) btn.append(document.createTextNode(text));
    return btn;
  }

  function formatTime(iso) {
    const d = iso ? new Date(iso) : new Date();
    if (Number.isNaN(d.getTime())) return "";
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return d.toDateString() === new Date().toDateString()
      ? time
      : `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${time}`;
  }

  let toastTimer = null;
  function toast(message) {
    dom.toast.textContent = message;
    dom.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { dom.toast.hidden = true; }, 1800);
  }

  function announce(message) { dom.liveStatus.textContent = message; }

  async function copyText(text, okMessage = "Copied to clipboard") {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = el("textarea"); // fallback for older browsers
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.append(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      if (!ok) return toast("Could not copy. Select the text and copy it manually.");
    }
    toast(okMessage);
  }

  // ---------- API ----------
  class ApiError extends Error {
    constructor(message, status, code) { super(message); this.status = status; this.code = code; }
  }

  async function readError(res) {
    let message = `The server returned an error (${res.status}).`, code = "";
    try {
      const data = await res.json();
      if (data.error) { message = data.error.message || message; code = data.error.code || ""; }
    } catch { /* body was not JSON */ }
    return new ApiError(message, res.status, code);
  }

  function networkError() {
    return new ApiError("Could not reach the server. Make sure the app is still running, then try again.", 0, "network");
  }

  async function api(path, { method = "GET", body } = {}) {
    let res;
    try {
      res = await fetch(path, {
        method,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch { throw networkError(); }
    if (!res.ok) throw await readError(res);
    return res.json();
  }

  // ---------- Markdown ----------
  if (window.DOMPurify) {
    window.DOMPurify.addHook("afterSanitizeAttributes", (node) => {
      if (node.tagName === "A") {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
      }
    });
  }
  if (window.marked) window.marked.setOptions({ gfm: true, breaks: true });

  function renderMarkdown(container, text, final) {
    if (!window.marked || !window.DOMPurify) { container.textContent = text; return; } // safe fallback
    container.innerHTML = window.DOMPurify.sanitize(window.marked.parse(text)); // sanitized first
    container.querySelectorAll("table").forEach((table) => {
      const wrap = el("div", "table-wrap");
      table.replaceWith(wrap);
      wrap.append(table);
    });
    if (final) enhanceCodeBlocks(container);
  }

  function enhanceCodeBlocks(container) {
    container.querySelectorAll("pre").forEach((pre) => {
      const code = pre.querySelector("code");
      if (!code) return;
      const langMatch = /language-([\w+#-]+)/.exec(code.className);
      const lang = langMatch ? langMatch[1] : "";
      if (window.hljs && lang && window.hljs.getLanguage(lang)) window.hljs.highlightElement(code);

      const block = el("div", "codeblock");
      const bar = el("div", "codeblock__bar");
      bar.append(el("span", "", lang || "code"));
      const copyBtn = iconButton("btn btn--ghost btn--small", "copy", "Copy code", "Copy");
      copyBtn.addEventListener("click", () => copyText(code.textContent, "Code copied"));
      bar.append(copyBtn);
      pre.replaceWith(block);
      block.append(bar, pre);
    });
  }

  // ---------- Messages ----------
  function atBottom() {
    const s = dom.scroll;
    return s.scrollHeight - s.scrollTop - s.clientHeight < 120;
  }
  dom.scroll.addEventListener("scroll", () => { state.stickToBottom = atBottom(); });

  function scrollToBottom(force = false) {
    if (force || state.stickToBottom) {
      dom.scroll.scrollTo({ top: dom.scroll.scrollHeight, behavior: "auto" });
    }
  }

  function messageEls() { return [...dom.thread.querySelectorAll(".msg:not([hidden])")]; }

  function refreshLastMarker() {
    dom.thread.querySelectorAll(".msg.is-last").forEach((m) => m.classList.remove("is-last"));
    const all = messageEls();
    const last = all[all.length - 1];
    if (last && last.classList.contains("msg--assistant")) last.classList.add("is-last");
  }

  function setAssistantText(msgEl, text, final) {
    msgEl.rawText = text;
    msgEl.toggleAttribute("data-empty", !text);
    const content = msgEl.querySelector(".msg__content");
    if (!text) return;
    renderMarkdown(content, text, final);
  }

  function appendMessage(role, text, createdAt, { pending = false, note = "" } = {}) {
    const msg = el("article", `msg msg--${role}`);
    const avatar = el("div", "msg__avatar");
    if (role === "assistant") {
      const img = el("img");
      img.src = document.querySelector('link[rel="icon"]').href;
      img.alt = "";
      avatar.append(img);
    } else {
      avatar.textContent = "Y";
    }

    const body = el("div", "msg__body");
    const head = el("div", "msg__head");
    head.append(el("span", "msg__name", role === "user" ? "You" : "Smart AI"));
    const time = el("time", "msg__time", pending ? "" : formatTime(createdAt));
    head.append(time);
    const content = el("div", "msg__content");
    body.append(head, content);

    if (role === "assistant") {
      const actions = el("div", "msg__actions");
      const copyBtn = iconButton("btn btn--ghost js-copy", "copy", "Copy response", "Copy");
      copyBtn.addEventListener("click", () => copyText(msg.rawText || "", "Response copied"));
      const regenBtn = iconButton("btn btn--ghost js-regen", "refresh", "Regenerate response", "Regenerate");
      regenBtn.addEventListener("click", () => sendMessage({ regenerate: true }));
      actions.append(copyBtn, regenBtn);
      body.append(actions);
    }
    msg.append(avatar, body);
    msg.rawText = "";
    dom.thread.append(msg);

    if (pending) {
      msg.classList.add("is-pending");
      const typing = el("span", "typing");
      typing.setAttribute("aria-hidden", "true");
      typing.append(el("span"), el("span"), el("span"));
      content.append(typing);
    } else if (role === "assistant") {
      if (note) { msg.classList.add("is-note"); content.textContent = note; msg.setAttribute("data-empty", ""); }
      else setAssistantText(msg, text, true);
    } else {
      content.textContent = text; // user text is never treated as HTML
    }
    refreshLastMarker();
    return msg;
  }

  function finishAssistant(msg, text, createdAt) {
    msg.classList.remove("is-pending");
    setAssistantText(msg, text, true);
    msg.querySelector(".msg__time").textContent = formatTime(createdAt);
    refreshLastMarker();
  }

  function showWelcome(show) { dom.welcome.hidden = !show; }

  function clearThread() {
    dom.thread.querySelectorAll(".msg").forEach((m) => m.remove());
  }

  // ---------- Errors ----------
  let retryAction = null;
  function showError(message, retry = null) {
    dom.errorText.textContent = message;
    retryAction = retry;
    dom.retryBtn.hidden = !retry;
    dom.errorBanner.hidden = false;
  }
  function clearError() { dom.errorBanner.hidden = true; retryAction = null; }
  dom.dismissErrorBtn.addEventListener("click", clearError);
  dom.retryBtn.addEventListener("click", () => { const action = retryAction; clearError(); if (action) action(); });

  // ---------- Composer ----------
  function autosize() {
    dom.input.style.height = "auto";
    dom.input.style.height = `${Math.min(dom.input.scrollHeight, 200)}px`;
  }

  function updateComposer() {
    const length = dom.input.value.length;
    dom.counter.textContent = `${length} / ${MAX_CHARS}`;
    dom.counter.classList.toggle("is-near", length > MAX_CHARS * 0.9);
    dom.sendBtn.disabled = state.busy || dom.input.value.trim() === "";
  }

  function setBusy(busy) {
    state.busy = busy;
    dom.sendBtn.hidden = busy;
    dom.stopBtn.hidden = !busy;
    dom.thread.querySelectorAll(".starter, .js-regen").forEach((b) => { b.disabled = busy; });
    updateComposer();
  }

  dom.input.addEventListener("input", () => { autosize(); updateComposer(); });
  dom.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      dom.form.requestSubmit();
    }
  });
  dom.form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.busy && dom.input.value.trim()) sendMessage({ text: dom.input.value });
  });
  dom.stopBtn.addEventListener("click", () => state.controller && state.controller.abort());

  dom.welcome.querySelectorAll(".starter").forEach((btn) =>
    btn.addEventListener("click", () => { if (!state.busy) sendMessage({ text: btn.dataset.prompt }); }));

  // ---------- Sending and streaming ----------
  async function readStream(res, onEvent) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (line) onEvent(JSON.parse(line));
      }
    }
    const tail = (buffer + decoder.decode()).trim();
    if (tail) onEvent(JSON.parse(tail));
  }

  async function sendMessage({ text = "", regenerate = false } = {}) {
    if (state.busy) return;
    clearError();
    text = text.trim();
    if (!regenerate && !text) return;
    if (!regenerate && text.length > MAX_CHARS) return showError(`Message is too long (maximum ${MAX_CHARS} characters).`);

    setBusy(true);
    const previousInput = dom.input.value;

    // A conversation is created on the first message (not when "New chat" is clicked).
    if (!state.activeId) {
      try {
        const created = await api("/api/conversations", { method: "POST", body: {} });
        state.activeId = created.conversation.id;
        setHash();
      } catch (err) {
        setBusy(false);
        return showError(err.message);
      }
    }

    showWelcome(false);
    const oldAssistant = regenerate ? [...dom.thread.querySelectorAll(".msg--assistant")].pop() || null : null;
    let userEl = null;
    if (!regenerate) {
      userEl = appendMessage("user", text, new Date().toISOString());
      dom.input.value = "";
      autosize();
      updateComposer();
    }
    if (oldAssistant) oldAssistant.hidden = true;
    const assistantEl = appendMessage("assistant", "", null, { pending: true });
    state.stickToBottom = true;
    scrollToBottom(true);
    announce("Smart AI is writing a reply.");

    state.controller = new AbortController();
    let received = "";
    let streamError = null;
    let done = null;
    let renderQueued = false;
    const queueRender = () => {
      if (renderQueued) return;
      renderQueued = true;
      requestAnimationFrame(() => {
        renderQueued = false;
        if (assistantEl.isConnected && assistantEl.classList.contains("is-pending")) {
          assistantEl.querySelector(".msg__content").classList.add("is-streaming");
          setAssistantText(assistantEl, received, false);
          scrollToBottom();
        }
      });
    };

    let reachedStream = false;
    try {
      let res;
      try {
        res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
          body: JSON.stringify(regenerate ? { conversation_id: state.activeId, regenerate: true }
                                          : { conversation_id: state.activeId, message: text }),
          signal: state.controller.signal,
        });
      } catch (err) {
        if (err.name === "AbortError") throw err;
        throw networkError();
      }
      if (!res.ok) throw await readError(res);

      reachedStream = true;
      if (oldAssistant) oldAssistant.remove(); // the server replaced it
      await readStream(res, (event) => {
        if (event.type === "delta") { received += event.text; queueRender(); }
        else if (event.type === "done") done = event;
        else if (event.type === "error") streamError = event;
      });
    } catch (err) {
      if (err.name === "AbortError") {
        if (oldAssistant) oldAssistant.remove();
        if (received) finishAssistant(assistantEl, received, new Date().toISOString());
        else { assistantEl.remove(); appendMessage("assistant", "", null, { note: "Generation stopped." }); }
        announce("Generation stopped.");
        await refreshConversations();
      } else if (!reachedStream) {
        // The request failed before anything was saved: undo the optimistic UI.
        assistantEl.remove();
        if (oldAssistant) oldAssistant.hidden = false;
        if (userEl) {
          userEl.remove();
          dom.input.value = text || previousInput; // give the text back so nothing is lost
          autosize();
          if (!messageEls().length) showWelcome(true);
        }
        refreshLastMarker();
        showError(err.message);
      } else {
        streamError = { message: "The connection was interrupted while the reply was being written." };
      }
    }

    if (done) {
      finishAssistant(assistantEl, done.message.content, done.message.created_at);
      if (done.title) dom.chatTitle.textContent = done.title;
      announce("Reply ready.");
      await refreshConversations();
    } else if (streamError) {
      if (received) finishAssistant(assistantEl, received, new Date().toISOString());
      else assistantEl.remove();
      refreshLastMarker();
      showError(streamError.message, () => sendMessage({ regenerate: true }));
      announce("The reply failed.");
      await refreshConversations();
    }

    state.controller = null;
    setBusy(false);
    scrollToBottom();
    dom.input.focus();
  }

  // ---------- Conversation list ----------
  function setHash() {
    history.replaceState(null, "", state.activeId ? `#c=${state.activeId}` : location.pathname + location.search);
  }

  function renderList() {
    dom.list.replaceChildren();
    const searching = dom.searchInput.value.trim() !== "";
    dom.listEmpty.hidden = state.conversations.length > 0;
    if (!state.conversations.length) {
      dom.listEmpty.textContent = searching
        ? "No conversations match your search."
        : "No conversations yet. Send a message to start your first one.";
    }
    for (const conv of state.conversations) {
      const li = el("li", "convo");
      li.classList.toggle("is-active", conv.id === state.activeId);
      const open = el("button", "convo__open");
      open.type = "button";
      open.append(el("span", "convo__title", conv.title));
      open.title = conv.title;
      if (conv.id === state.activeId) open.setAttribute("aria-current", "true");
      open.addEventListener("click", () => openConversation(conv.id));

      const actions = el("div", "convo__actions");
      const rename = iconButton("btn btn--ghost", "edit", `Rename ${conv.title}`);
      rename.addEventListener("click", () => openRename(conv));
      const del = iconButton("btn btn--ghost", "trash", `Delete ${conv.title}`);
      del.addEventListener("click", () => openDelete(conv));
      actions.append(rename, del);
      li.append(open, actions);
      dom.list.append(li);
    }
  }

  async function refreshConversations() {
    try {
      const q = dom.searchInput.value.trim();
      const data = await api(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ""}`);
      state.conversations = data.conversations;
      renderList();
    } catch (err) {
      showError(err.message);
    }
  }

  dom.searchInput.addEventListener("input", () => {
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(refreshConversations, 250);
  });

  function startNewChat() {
    if (state.busy) return;
    state.activeId = null;
    setHash();
    clearThread();
    clearError();
    dom.chatTitle.textContent = DEFAULT_TITLE;
    showWelcome(true);
    renderList();
    closeSidebar();
    dom.input.focus();
  }
  dom.newChatBtn.addEventListener("click", startNewChat);

  async function openConversation(id) {
    if (state.busy) return;
    try {
      const data = await api(`/api/conversations/${id}`);
      state.activeId = data.conversation.id;
      setHash();
      clearThread();
      clearError();
      dom.chatTitle.textContent = data.conversation.title;
      showWelcome(data.messages.length === 0);
      for (const m of data.messages) appendMessage(m.role, m.content, m.created_at);
      state.stickToBottom = true;
      scrollToBottom(true);
      renderList();
      closeSidebar();
    } catch (err) {
      if (err.status === 404 || err.status === 400) { startNewChat(); }
      showError(err.message);
    }
  }

  // ---------- Rename / delete ----------
  function openRename(conv) {
    state.pendingRename = conv;
    dom.renameInput.value = conv.title;
    dom.renameDialog.showModal();
    dom.renameInput.select();
  }
  dom.renameForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const conv = state.pendingRename;
    if (!conv) return;
    try {
      const data = await api(`/api/conversations/${conv.id}`, { method: "PATCH", body: { title: dom.renameInput.value } });
      dom.renameDialog.close();
      if (conv.id === state.activeId) dom.chatTitle.textContent = data.conversation.title;
      await refreshConversations();
      toast("Conversation renamed");
    } catch (err) {
      dom.renameDialog.close();
      showError(err.message);
    }
  });

  function openDelete(conv) {
    state.pendingDelete = conv;
    dom.deleteText.textContent = `“${conv.title}” and all of its messages will be permanently deleted.`;
    dom.deleteDialog.showModal();
  }
  dom.confirmDeleteBtn.addEventListener("click", async () => {
    const conv = state.pendingDelete;
    if (!conv) return;
    try {
      await api(`/api/conversations/${conv.id}`, { method: "DELETE" });
      dom.deleteDialog.close();
      if (conv.id === state.activeId) startNewChat();
      await refreshConversations();
      toast("Conversation deleted");
    } catch (err) {
      dom.deleteDialog.close();
      showError(err.message);
    }
  });

  // ---------- Dialog plumbing ----------
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); }); // backdrop click
    dialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
  });

  // ---------- Settings and theme ----------
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const next = theme === "dark" ? "light" : "dark";
    dom.themeBtn.setAttribute("aria-label", `Switch to ${next} theme`);
    dom.themeBtn.title = `Switch to ${next} theme`;
  }

  function renderSettings(data) {
    state.settings = data.settings;
    state.ai = data.ai;
    applyTheme(data.settings.theme);
    dom.themeSelect.value = data.settings.theme;
    dom.styleSelect.value = data.settings.response_style;
    dom.configNotice.hidden = data.ai.configured;
    dom.modelChip.hidden = !data.ai.configured;
    dom.modelChip.textContent = data.ai.model ? `Model: ${data.ai.model}` : "";
    dom.aiInfo.textContent = data.ai.configured
      ? `Connected to model “${data.ai.model}”. The API key is read from your .env file and never reaches the browser.`
      : "The AI is not configured. Add OPENAI_API_KEY and OPENAI_MODEL to .env, then restart the app.";
  }

  async function saveSetting(patch) {
    try {
      renderSettings(await api("/api/settings", { method: "PUT", body: patch }));
      toast("Settings saved");
    } catch (err) {
      showError(err.message);
      renderSettings({ settings: state.settings, ai: state.ai });
    }
  }
  dom.themeBtn.addEventListener("click", () => saveSetting({ theme: state.settings.theme === "dark" ? "light" : "dark" }));
  dom.themeSelect.addEventListener("change", () => saveSetting({ theme: dom.themeSelect.value }));
  dom.styleSelect.addEventListener("change", () => saveSetting({ response_style: dom.styleSelect.value }));
  dom.settingsBtn.addEventListener("click", () => { closeSidebar(); dom.settingsDialog.showModal(); });

  // ---------- Mobile sidebar ----------
  function openSidebar() {
    document.body.classList.add("sidebar-open");
    dom.scrim.hidden = false;
    dom.menuBtn.setAttribute("aria-expanded", "true");
  }
  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
    dom.scrim.hidden = true;
    dom.menuBtn.setAttribute("aria-expanded", "false");
  }
  dom.menuBtn.addEventListener("click", openSidebar);
  dom.scrim.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeSidebar(); });

  // ---------- Start-up ----------
  async function init() {
    updateComposer();
    try {
      renderSettings(await api("/api/settings"));
    } catch (err) {
      showError(err.message);
    }
    await refreshConversations();
    const match = /^#c=([0-9a-f]{32})$/.exec(location.hash);
    if (match) await openConversation(match[1]);
    dom.input.focus();
  }
  init();
})();
