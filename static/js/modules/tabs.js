function select(tablist, tab, focus) {
  tablist.querySelectorAll('[role="tab"]').forEach((item) => {
    const active = item === tab;
    item.setAttribute("aria-selected", String(active));
    item.tabIndex = active ? 0 : -1;
    document.getElementById(item.getAttribute("aria-controls")).hidden = !active;
  });
  if (focus) {
    tab.focus();
  }
}

export function initTabs(root) {
  root.querySelectorAll('[role="tablist"]:not([data-ready])').forEach((tablist) => {
    tablist.dataset.ready = "true";
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];

    tablist.addEventListener("click", (event) => {
      const tab = event.target.closest('[role="tab"]');
      if (tab) {
        select(tablist, tab, false);
      }
    });

    tablist.addEventListener("keydown", (event) => {
      const index = tabs.indexOf(document.activeElement);
      const moves = { ArrowRight: 1, ArrowLeft: -1, Home: -index, End: tabs.length - 1 - index };
      if (index === -1 || !(event.key in moves)) {
        return;
      }
      event.preventDefault();
      select(tablist, tabs[(index + moves[event.key] + tabs.length) % tabs.length], true);
    });
  });
}
