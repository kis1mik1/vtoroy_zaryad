import { showToast } from "./toasts.js";

const MAX_DELAY = 30000;

function setCount(value) {
  document.querySelectorAll("[data-notifications-count]").forEach((badge) => {
    badge.textContent = value > 99 ? "99+" : String(value);
    badge.hidden = value === 0;
  });
}

function handle(event) {
  if (event.type === "notification") {
    setCount(event.unread);
    showToast(event.title, "info", event.url);
    const list = document.querySelector("[data-live-notices]");
    if (list) {
      list.insertAdjacentHTML("afterbegin", event.html);
      list.hidden = false;
      document.querySelector("[data-live-empty]")?.remove();
    }
  } else if (event.type === "notification_read") {
    setCount(event.unread);
  }
}

function connect(url, attempt = 0) {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}${url}`);

  socket.addEventListener("open", () => {
    attempt = 0;
  });
  socket.addEventListener("message", (message) => {
    try {
      handle(JSON.parse(message.data));
    } catch {
      return;
    }
  });
  socket.addEventListener("close", (event) => {
    if (event.code === 4401) {
      return;
    }
    const delay = Math.min(MAX_DELAY, 1000 * 2 ** attempt) + Math.random() * 1000;
    setTimeout(() => connect(url, attempt + 1), delay);
  });
}

export function initLive() {
  document.addEventListener("notifications-count", (event) => setCount(event.detail.value));
  const url = document.body.dataset.liveUrl;
  if (url) {
    connect(url);
  }
}
