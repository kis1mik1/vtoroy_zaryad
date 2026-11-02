function normalize(value) {
  return value.toLowerCase().replaceAll("ё", "е").trim();
}

export function initFilterList() {
  document.addEventListener("input", (event) => {
    const input = event.target.closest("[data-filter-input]");
    if (!input) {
      return;
    }
    const list = document.getElementById(input.dataset.filterInput);
    const query = normalize(input.value);
    let visible = 0;

    list.querySelectorAll("[data-filter-item]").forEach((item) => {
      const match = normalize(item.dataset.filterItem).includes(query);
      item.hidden = !match;
      visible += match ? 1 : 0;
    });
    list.querySelectorAll("[data-filter-group]").forEach((group) => {
      group.hidden = !group.querySelector("[data-filter-item]:not([hidden])");
    });
    list.querySelector("[data-filter-empty]")?.toggleAttribute("hidden", visible > 0);
  });
}
