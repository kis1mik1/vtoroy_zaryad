import { showToast } from "./toasts.js";
import { initVoiceRecorder } from "./voice.js";

const MAX_DELAY = 30000;

function csrfToken() {
  return document.querySelector("[name=csrfmiddlewaretoken]")?.value ?? "";
}

export async function postForm(url, body) {
  const response = await fetch(url, {
    method: "POST",
    body,
    headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "fetch" },
  });
  const text = await response.text();
  if (!response.ok) {
    showToast(text || "Не удалось отправить, попробуйте ещё раз.", "error");
    return null;
  }
  return text;
}

export function initChat() {
  const root = document.querySelector("[data-chat]");
  if (!root) {
    return;
  }
  const list = root.querySelector("[data-chat-messages]");
  const form = root.querySelector("[data-chat-form]");
  const input = root.querySelector("[data-chat-input]");
  let socket = null;

  const scrollDown = () => {
    list.scrollTop = list.scrollHeight;
  };

  const markRead = () => {
    if (document.visibilityState === "visible" && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "read" }));
    }
  };

  const append = (html) => {
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    const item = template.content.firstElementChild;
    if (!item || list.querySelector(`[data-message-id="${item.dataset.messageId}"]`)) {
      return;
    }
    list.querySelector("[data-chat-empty]")?.remove();
    if (item.dataset.mine === "true" && item.dataset.kind === "voice") {
      list.querySelector("[data-voice-pending]")?.remove();
    }
    list.append(item);
    scrollDown();
    if (item.dataset.mine === "false") {
      markRead();
    }
  };

  const handle = (event) => {
    if (event.type === "message") {
      append(event.html);
    } else if (event.type === "read") {
      list.querySelectorAll(".msg--mine [data-status]").forEach((status) => {
        status.textContent = "прочитано";
      });
    } else if (event.type === "error") {
      list.querySelector("[data-voice-pending]")?.remove();
      showToast(event.text, "error");
    }
  };

  const connect = (attempt = 0) => {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}${root.dataset.socket}`);
    socket.addEventListener("open", () => {
      attempt = 0;
      markRead();
    });
    socket.addEventListener("message", (message) => handle(JSON.parse(message.data)));
    socket.addEventListener("close", (event) => {
      if (event.code === 4401 || event.code === 4403) {
        return;
      }
      const delay = Math.min(MAX_DELAY, 1000 * 2 ** attempt) + Math.random() * 1000;
      setTimeout(() => connect(attempt + 1), delay);
    });
  };

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) {
      return;
    }
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "send", text }));
    } else {
      const html = await postForm(form.action, new FormData(form));
      if (html === null) {
        return;
      }
      append(html);
    }
    input.value = "";
    input.style.height = "";
  });

  input?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  input?.addEventListener("input", () => {
    input.style.height = "";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  });

  root.querySelector("[data-chat-photo]")?.addEventListener("change", async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    const data = new FormData();
    data.append("photo", file);
    const html = await postForm(event.target.dataset.url, data);
    if (html) {
      append(html);
    }
  });

  initVoiceRecorder(root, list);
  document.addEventListener("visibilitychange", markRead);
  scrollDown();
  connect();
}
