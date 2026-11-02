export function initFilters() {
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-filters-open]")) {
      document.body.dataset.filtersOpen = "";
    } else if (event.target.closest("[data-filters-close]")) {
      delete document.body.dataset.filtersOpen;
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && "filtersOpen" in document.body.dataset) {
      delete document.body.dataset.filtersOpen;
    }
  });
}
