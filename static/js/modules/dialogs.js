function closeOnBackdrop(dialog) {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      dialog.close();
    }
  });
}

export function initDialogs() {
  document.querySelectorAll("dialog.modal").forEach(closeOnBackdrop);

  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-open-dialog]");
    if (opener) {
      document.getElementById(opener.dataset.openDialog)?.showModal();
      return;
    }
    const closer = event.target.closest("[data-close-dialog]");
    if (closer) {
      closer.closest("dialog")?.close();
    }
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target.id !== "modal-content") {
      return;
    }
    const modal = document.getElementById("modal");
    if (!modal.open) {
      modal.showModal();
    }
    modal.querySelector("[autofocus]")?.focus();
  });

  document.getElementById("modal")?.addEventListener("close", (event) => {
    event.target.querySelector("#modal-content").replaceChildren();
  });
}
