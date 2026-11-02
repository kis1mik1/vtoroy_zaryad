const COOKIE = "theme";
const YEAR = 60 * 60 * 24 * 365;

function applyTheme(value) {
  const root = document.documentElement;
  if (value) {
    root.dataset.theme = value;
    document.cookie = `${COOKIE}=${value}; path=/; max-age=${YEAR}; samesite=lax`;
  } else {
    delete root.dataset.theme;
    document.cookie = `${COOKIE}=; path=/; max-age=0; samesite=lax`;
  }
  document.querySelectorAll("[data-theme-choice]").forEach((item) => {
    item.setAttribute("aria-checked", String(item.dataset.themeChoice === value));
  });
}

export function initTheme() {
  document.addEventListener("click", (event) => {
    const choice = event.target.closest("[data-theme-choice]");
    if (choice) {
      applyTheme(choice.dataset.themeChoice);
    }
  });
}
