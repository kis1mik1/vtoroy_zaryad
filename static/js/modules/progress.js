export function initProgress() {
  const bar = document.getElementById("progress-bar");
  if (!bar) {
    return;
  }
  let active = 0;

  document.addEventListener("htmx:beforeRequest", () => {
    active += 1;
    bar.classList.remove("is-done");
    bar.classList.add("is-active");
  });

  document.addEventListener("htmx:afterRequest", () => {
    active = Math.max(0, active - 1);
    if (active === 0) {
      bar.classList.remove("is-active");
      bar.classList.add("is-done");
    }
  });
}
