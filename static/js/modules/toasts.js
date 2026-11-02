const LIFETIME = 5000;

function dismiss(toast) {
  if (toast.classList.contains("is-leaving")) {
    return;
  }
  toast.classList.add("is-leaving");
  toast.addEventListener("transitionend", () => toast.remove(), { once: true });
}

function schedule(root) {
  root.querySelectorAll("[data-toast]:not([data-scheduled])").forEach((toast) => {
    toast.dataset.scheduled = "true";
    let timer = setTimeout(() => dismiss(toast), LIFETIME);
    toast.addEventListener("mouseenter", () => clearTimeout(timer));
    toast.addEventListener("mouseleave", () => {
      timer = setTimeout(() => dismiss(toast), LIFETIME / 2);
    });
  });
}

export function showToast(text, level = "info", url = "") {
  const container = document.getElementById("toasts");
  const template = document.getElementById(`toast-template-${level}`);
  if (!container || !template) {
    return;
  }
  const toast = template.content.firstElementChild.cloneNode(true);
  const label = toast.querySelector(".toast__text");
  if (url) {
    const link = document.createElement("a");
    link.href = url;
    link.textContent = text;
    label.append(link);
  } else {
    label.textContent = text;
  }
  container.append(toast);
}

export function initToasts() {
  const container = document.getElementById("toasts");
  if (!container) {
    return;
  }
  schedule(container);
  new MutationObserver(() => schedule(container)).observe(container, { childList: true });

  document.addEventListener("toast", (event) => {
    showToast(event.detail.text, event.detail.level);
  });

  document.addEventListener("htmx:responseError", (event) => {
    if (event.detail.xhr.status >= 500) {
      showToast("Не получилось выполнить действие. Попробуйте ещё раз.", "error");
    }
  });

  document.addEventListener("htmx:sendError", () => {
    showToast("Нет связи с сервером. Проверьте интернет.", "error");
  });

  container.addEventListener("click", (event) => {
    const button = event.target.closest("[data-toast-close]");
    if (button) {
      dismiss(button.closest("[data-toast]"));
    }
  });
}
