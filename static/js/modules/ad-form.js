function syncCondition(form) {
  const checked = form.querySelector('[name="condition"]:checked');
  form.querySelectorAll("[data-condition-only]").forEach((group) => {
    group.hidden = !checked || group.dataset.conditionOnly !== checked.value;
  });
}

function syncToggles(form) {
  form.querySelectorAll("[data-toggle-by]").forEach((block) => {
    const source = document.getElementById(block.dataset.toggleBy);
    if (!source) {
      return;
    }
    const wanted = block.dataset.toggleWhen === "checked";
    block.hidden = source.checked !== wanted;
  });
}

function syncCustomModel(form) {
  const select = form.querySelector("[data-model-select]");
  const custom = form.querySelector("[data-custom-model]");
  if (select && custom) {
    custom.hidden = select.value !== "other";
  }
}

function sync(form) {
  syncCondition(form);
  syncToggles(form);
  syncCustomModel(form);
}

function initCategoryPicker(form) {
  const picker = form.querySelector("[data-category-picker]");
  if (!picker) {
    return;
  }
  picker.addEventListener("change", (event) => {
    if (event.target.name !== "category") {
      return;
    }
    const label = event.target.closest("label").textContent.trim();
    picker.querySelector("[data-category-name]").textContent = label;
    picker.classList.add("is-collapsed");
  });
  picker.querySelector("[data-category-expand]").addEventListener("click", () => {
    picker.classList.remove("is-collapsed");
    picker.querySelector("input:checked")?.focus();
  });
}

export function initAdForm() {
  const form = document.querySelector("[data-ad-form]");
  if (!form) {
    return;
  }
  initCategoryPicker(form);
  sync(form);
  form.addEventListener("change", () => sync(form));
  document.addEventListener("htmx:afterSettle", () => sync(form));
}
