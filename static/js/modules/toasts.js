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

export function initToasts() {
  const container = document.getElementById("toasts");
  if (!container) {
    return;
  }
  schedule(container);
  new MutationObserver(() => schedule(container)).observe(container, { childList: true });

  container.addEventListener("click", (event) => {
    const button = event.target.closest("[data-toast-close]");
    if (button) {
      dismiss(button.closest("[data-toast]"));
    }
  });
}
