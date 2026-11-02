export function initAvatarInput() {
  document.addEventListener("change", (event) => {
    const input = event.target.closest("[data-avatar-input]");
    if (!input || !input.files.length) {
      return;
    }
    const file = input.files[0];
    const field = input.closest(".avatar-field");
    field.querySelector("[data-avatar-name]").textContent = file.name;

    const avatar = field.querySelector(".avatar");
    if (!file.type.startsWith("image/") || file.type === "image/heic") {
      return;
    }
    const image = document.createElement("img");
    image.alt = "";
    image.src = URL.createObjectURL(file);
    image.addEventListener("load", () => URL.revokeObjectURL(image.src), { once: true });
    avatar.replaceChildren(image);
  });
}
