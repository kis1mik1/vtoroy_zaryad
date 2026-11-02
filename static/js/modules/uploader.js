function csrfToken() {
  return document.querySelector("[name=csrfmiddlewaretoken]")?.value ?? "";
}

function tiles(list) {
  return [...list.querySelectorAll("[data-photo]")];
}

function setErrors(root, messages) {
  const box = root.querySelector("[data-photo-errors]");
  box.replaceChildren(
    ...messages.map((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      return item;
    }),
  );
}

function refresh(root) {
  const list = root.querySelector("[data-photo-list]");
  const max = Number(root.dataset.max);
  const count = list.querySelectorAll("[data-photo]:not(.is-failed)").length;
  root.querySelector("[data-photo-drop]").hidden = count >= max;
}

async function upload(root, file) {
  const list = root.querySelector("[data-photo-list]");
  const placeholder = document.createElement("li");
  placeholder.className = "photo-tile is-uploading";
  placeholder.dataset.photo = "";
  list.append(placeholder);
  refresh(root);

  const body = new FormData();
  body.append("photo", file);
  try {
    const response = await fetch(root.dataset.url, {
      method: "POST",
      body,
      headers: { "X-CSRFToken": csrfToken() },
      credentials: "same-origin",
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(response.status === 429 ? "Слишком много загрузок, подождите немного." : text);
    }
    const template = document.createElement("template");
    template.innerHTML = text.trim();
    placeholder.replaceWith(template.content.firstElementChild);
  } catch (error) {
    placeholder.remove();
    const reason = error.message || "Не удалось загрузить фото.";
    return `${file.name}: ${reason.length > 200 ? "не удалось загрузить фото." : reason}`;
  } finally {
    refresh(root);
  }
  return null;
}

async function handleFiles(root, files) {
  const list = root.querySelector("[data-photo-list]");
  const free = Number(root.dataset.max) - tiles(list).length;
  const accepted = [...files].slice(0, Math.max(free, 0));
  const errors = [];
  if (files.length > accepted.length) {
    errors.push(`Можно добавить не больше ${root.dataset.max} фото.`);
  }
  setErrors(root, errors);
  for (const file of accepted) {
    const error = await upload(root, file);
    if (error) {
      errors.push(error);
      setErrors(root, errors);
    }
  }
}

function enableSorting(root) {
  const list = root.querySelector("[data-photo-list]");
  let dragged = null;

  list.addEventListener("pointerdown", (event) => {
    const tile = event.target.closest("[data-photo]");
    if (!tile || event.pointerType !== "mouse" || event.target.closest("button") || event.button !== 0) {
      return;
    }
    dragged = tile;
    tile.setPointerCapture(event.pointerId);
    tile.classList.add("is-dragging");
  });

  list.addEventListener("pointermove", (event) => {
    if (!dragged) {
      return;
    }
    const over = document.elementFromPoint(event.clientX, event.clientY)?.closest("[data-photo]");
    if (!over || over === dragged || over.parentElement !== list) {
      return;
    }
    const items = tiles(list);
    const after = items.indexOf(over) > items.indexOf(dragged);
    over[after ? "after" : "before"](dragged);
  });

  const stop = () => {
    dragged?.classList.remove("is-dragging");
    dragged = null;
  };
  list.addEventListener("pointerup", stop);
  list.addEventListener("pointercancel", stop);
  list.addEventListener("dragstart", (event) => event.preventDefault());

  list.addEventListener("click", (event) => {
    const tile = event.target.closest("[data-photo]");
    if (!tile) {
      return;
    }
    if (event.target.closest("[data-photo-remove]")) {
      tile.remove();
      refresh(root);
      return;
    }
    const move = event.target.closest("[data-photo-move]");
    if (move) {
      const items = tiles(list);
      const target = items[items.indexOf(tile) + Number(move.dataset.photoMove)];
      if (target) {
        target[Number(move.dataset.photoMove) > 0 ? "after" : "before"](tile);
        move.focus();
      }
    }
  });
}

export function initUploader() {
  document.querySelectorAll("[data-uploader]").forEach((root) => {
    const input = root.querySelector("[data-photo-input]");
    const drop = root.querySelector("[data-photo-drop]");

    input.addEventListener("change", () => {
      handleFiles(root, input.files);
      input.value = "";
    });
    drop.addEventListener("dragover", (event) => {
      event.preventDefault();
      drop.classList.add("is-over");
    });
    drop.addEventListener("dragleave", () => drop.classList.remove("is-over"));
    drop.addEventListener("drop", (event) => {
      event.preventDefault();
      drop.classList.remove("is-over");
      handleFiles(root, event.dataTransfer.files);
    });

    enableSorting(root);
    refresh(root);
  });
}
