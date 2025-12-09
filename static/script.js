// static/script.js
// Updated chat client with robust scroll handling, MCP fallback and "new messages" indicator.

document.addEventListener("DOMContentLoaded", initChat);

function initChat() {
  const chatbox = document.getElementById("chatbox");
  const sendBtn = document.getElementById("send-btn");
  const clearBtn = document.getElementById("clear-btn");
  const history = document.getElementById("chat-history");

  // Create "new messages" button if missing
  let newMsgBtn = document.getElementById("new-msg-btn");
  if (!newMsgBtn) {
    newMsgBtn = document.createElement("button");
    newMsgBtn.id = "new-msg-btn";
    newMsgBtn.className = "new-msg-btn";
    newMsgBtn.textContent = "New messages ▼";
    newMsgBtn.style.display = "none";
    newMsgBtn.addEventListener("click", () => {
      scrollToBottomSmooth(history);
      newMsgBtn.style.display = "none";
    });
    history.parentElement.insertBefore(newMsgBtn, history.nextSibling);
  }

  // Enter = send, Shift+Enter = newline
  chatbox?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      askBot();
    }
  });

  sendBtn?.addEventListener("click", askBot);
  clearBtn?.addEventListener("click", () => {
    history.innerHTML = "";
    chatbox.value = "";
    scrollToBottom(history);
  });

  // Show/hide new-message button depending on scroll
  let scrollTimeout = null;
  history.addEventListener("scroll", () => {
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(() => {
      if (isUserNearBottom(history, 80)) {
        hideNewMessageIndicator();
      }
    }, 80);
  });

  // initial focus
  chatbox?.focus();
}

// --- Utilities ------------------------------------------------------------

function isUserNearBottom(container, thresholdPx = 40) {
  const scrollPosition = container.scrollTop + container.clientHeight;
  const bottomPosition = container.scrollHeight;
  return (bottomPosition - scrollPosition) <= thresholdPx;
}

function scrollToBottom(container) {
  container.scrollTop = container.scrollHeight;
}

function scrollToBottomSmooth(container) {
  try {
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  } catch (e) {
    container.scrollTop = container.scrollHeight;
  }
}

/**
 * Scroll `container` so that `el`'s top is visible near the top of the container.
 * If user is not near bottom and force===false, do nothing and return false.
 * Returns true if scroll happened.
 */
function scrollElementTopIntoView(el, container, { force = false, margin = 8 } = {}) {
  if (!force && !isUserNearBottom(container, 120)) return false;

  try {
    const elRect = el.getBoundingClientRect();
    const contRect = container.getBoundingClientRect();
    const offsetTop = elRect.top - contRect.top + container.scrollTop;
    let target = Math.max(0, Math.floor(offsetTop - margin));
    const maxTop = Math.max(0, container.scrollHeight - container.clientHeight);
    if (target > maxTop) target = maxTop;
    container.scrollTo({ top: target, behavior: "smooth" });
    return true;
  } catch (err) {
    // fallback - go to bottom
    scrollToBottomSmooth(container);
    return true;
  }
}

function showNewMessageIndicator() {
  const btn = document.getElementById("new-msg-btn");
  if (btn) btn.style.display = "inline-block";
}

function hideNewMessageIndicator() {
  const btn = document.getElementById("new-msg-btn");
  if (btn) btn.style.display = "none";
}

function escapeHTML(str) {
  return String(str).replace(/[&<>"']/g, (m) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m] || m)
  );
}

// --- Message DOM helpers --------------------------------------------------

function appendUserMessage(text) {
  const history = document.getElementById("chat-history");
  const wrapper = document.createElement("div");
  wrapper.className = "message user message-appear";
  wrapper.innerHTML = `<div class="bubble"><div class="role">You</div>${escapeHTML(text)}</div>`;
  history.appendChild(wrapper);

  // If user near bottom, align top of this user message in view (so answer start is visible later)
  const scrolled = scrollElementTopIntoView(wrapper, history, { force: false, margin: 12 });
  if (!scrolled) showNewMessageIndicator();
}

function appendBotLoading() {
  const history = document.getElementById("chat-history");
  const wrapper = document.createElement("div");
  wrapper.className = "message bot message-appear";
  wrapper.innerHTML = `<div class="bubble bot-message loading"><span class="spinner"></span>Thinking…</div>`;
  history.appendChild(wrapper);

  const scrolled = scrollElementTopIntoView(wrapper, history, { force: false, margin: 12 });
  if (!scrolled) showNewMessageIndicator();
  return wrapper;
}

function replaceBotLoadingWithHtml(html) {
  const history = document.getElementById("chat-history");
  const loading = history.querySelector(".bot-message.loading");
  const wrapper = document.createElement("div");
  wrapper.className = "message bot message-appear";
  wrapper.innerHTML = `<div class="bubble"><div class="role">GIKI Bot</div>${html}</div>`;

  if (loading) {
    loading.parentElement.replaceWith(wrapper);
  } else {
    history.appendChild(wrapper);
  }

  // If user near bottom, ensure the TOP of the answer is visible
  const scrolled = scrollElementTopIntoView(wrapper, history, { force: false, margin: 8 });
  if (!scrolled) showNewMessageIndicator();
  else hideNewMessageIndicator();
}

function appendBotError(err) {
  const history = document.getElementById("chat-history");
  const wrapper = document.createElement("div");
  wrapper.className = "message bot message-appear";
  wrapper.innerHTML = `<div class="bubble"><div class="role">GIKI Bot</div><em style="color:#b91c1c">Error:</em> ${escapeHTML(err)}</div>`;
  history.appendChild(wrapper);
  const scrolled = scrollElementTopIntoView(wrapper, history, { force: false, margin: 8 });
  if (!scrolled) showNewMessageIndicator();
}

// --- Main send logic (mcp fallback) --------------------------------------

function askBot() {
  const chatbox = document.getElementById("chatbox");
  const query = chatbox.value.trim();
  const history = document.getElementById("chat-history");
  if (!query) return;

  // optional top_k selector
  const topkEl = document.getElementById("topk");
  const top_k = topkEl ? parseInt(topkEl.value || "3", 10) : 3;

  appendUserMessage(query);
  chatbox.value = "";
  appendBotLoading();

  const payload = { input: query, top_k: top_k };

  // try /mcp first, fallback to /chat on 404 or error JSON
  fetch("/mcp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((res) => {
      if (res.status === 404) return null; // missing endpoint -> fallback
      if (!res.ok) {
        // try to parse JSON error; if parsing fails, treat as error
        return res.json().catch(() => {
          throw new Error(`Server returned ${res.status}`);
        });
      }
      return res.json();
    })
    .then((jsonOrNull) => {
      if (jsonOrNull === null) {
        // call /chat
        return fetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: query, top_k: top_k }),
        })
          .then((r) => {
            if (!r.ok) throw new Error(`/chat returned ${r.status}`);
            return r.json();
          })
          .then((data) => {
            const ansHtml = data.answer || data?.answer_html || "Sorry, no answer received.";
            replaceBotLoadingWithHtml(ansHtml);
          });
      } else {
        const json = jsonOrNull;
        if (json.status === "ok" && json.answer) {
          replaceBotLoadingWithHtml(json.answer);
          return;
        }
        // MCP returned an error object — fallback to /chat
        return fetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: query, top_k: top_k }),
        })
          .then((r) => {
            if (!r.ok) throw new Error(`/chat returned ${r.status}`);
            return r.json();
          })
          .then((data) => {
            const ansHtml = data.answer || data?.answer_html || "Sorry, no answer received.";
            replaceBotLoadingWithHtml(ansHtml);
          });
      }
    })
    .catch((err) => {
      // Remove loading indicator if present
      const historyEl = document.getElementById("chat-history");
      const loadingDiv = historyEl.querySelector(".bot-message.loading");
      if (loadingDiv) loadingDiv.remove();
      appendBotError(err.message || String(err));
    });
}
