export function initConfirm() {
  const dialog = document.getElementById("confirm-dialog");
  if (!dialog) {
    return;
  }
  const text = dialog.querySelector("#confirm-text");
  const accept = dialog.querySelector("#confirm-accept");
  let pending = null;

  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      if (!form.dataset.confirm || form.dataset.confirmed === "true") {
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      pending = { form, submitter: event.submitter };
      text.textContent = form.dataset.confirm;
      accept.textContent = form.dataset.confirmAction || "Подтвердить";
      dialog.returnValue = "";
      dialog.showModal();
    },
    true,
  );

  dialog.addEventListener("close", () => {
    if (dialog.returnValue === "confirm" && pending) {
      const { form, submitter } = pending;
      form.dataset.confirmed = "true";
      form.requestSubmit(submitter);
      delete form.dataset.confirmed;
    }
    pending = null;
  });
}
