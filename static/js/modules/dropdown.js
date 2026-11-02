function close(dropdown) {
  const toggle = dropdown.querySelector("[data-dropdown-toggle]");
  const menu = dropdown.querySelector("[data-dropdown-menu]");
  toggle.setAttribute("aria-expanded", "false");
  menu.hidden = true;
}

function closeAll(except) {
  document.querySelectorAll("[data-dropdown]").forEach((dropdown) => {
    if (dropdown !== except) {
      close(dropdown);
    }
  });
}

function items(menu) {
  return [...menu.querySelectorAll("a, button:not([disabled])")];
}

export function initDropdowns() {
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-dropdown-toggle]");
    const dropdown = event.target.closest("[data-dropdown]");

    if (toggle) {
      const menu = dropdown.querySelector("[data-dropdown-menu]");
      const opening = menu.hidden;
      closeAll(dropdown);
      menu.hidden = !opening;
      toggle.setAttribute("aria-expanded", String(opening));
      if (opening) {
        menu.dispatchEvent(new CustomEvent("dropdown:open"));
      }
      if (opening && event.detail === 0) {
        items(menu)[0]?.focus();
      }
      return;
    }

    if (!dropdown || event.target.closest("[data-dropdown-menu] a, [data-dropdown-menu] button")) {
      closeAll();
    }
  });

  document.addEventListener("keydown", (event) => {
    const dropdown = event.target.closest?.("[data-dropdown]");
    if (!dropdown) {
      return;
    }
    const menu = dropdown.querySelector("[data-dropdown-menu]");
    if (menu.hidden) {
      return;
    }
    if (event.key === "Escape") {
      close(dropdown);
      dropdown.querySelector("[data-dropdown-toggle]").focus();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const list = items(menu);
      const index = list.indexOf(document.activeElement);
      const step = event.key === "ArrowDown" ? 1 : -1;
      list[(index + step + list.length) % list.length]?.focus();
    }
  });
}
