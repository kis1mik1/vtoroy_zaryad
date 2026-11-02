function setup(root) {
  const track = root.querySelector("[data-gallery-track]");
  const slides = [...track.children];
  const thumbs = [...root.querySelectorAll("[data-gallery-thumb]")];
  const counter = root.querySelector("[data-gallery-counter]");
  const lightbox = root.querySelector("[data-gallery-lightbox]");
  const image = lightbox.querySelector("[data-lightbox-image]");
  const lightCounter = lightbox.querySelector("[data-lightbox-counter]");
  const sources = JSON.parse(root.querySelector("[data-gallery-images]").textContent);
  let current = 0;
  let zoomed = 0;

  const show = (index, smooth = true) => {
    current = (index + slides.length) % slides.length;
    track.scrollTo({ left: slides[current].offsetLeft, behavior: smooth ? "smooth" : "auto" });
  };

  const mark = () => {
    thumbs.forEach((thumb, i) => thumb.classList.toggle("is-active", i === current));
    if (counter) {
      counter.textContent = `${current + 1} / ${slides.length}`;
    }
  };

  track.addEventListener("scroll", () => {
    const index = Math.round(track.scrollLeft / track.clientWidth);
    if (index !== current) {
      current = index;
      mark();
    }
  }, { passive: true });

  root.querySelector("[data-gallery-prev]")?.addEventListener("click", () => show(current - 1));
  root.querySelector("[data-gallery-next]")?.addEventListener("click", () => show(current + 1));
  thumbs.forEach((thumb, i) => thumb.addEventListener("click", () => show(i)));
  track.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight") show(current + 1);
    if (event.key === "ArrowLeft") show(current - 1);
  });

  const zoom = (index) => {
    zoomed = (index + sources.length) % sources.length;
    image.src = sources[zoomed];
    image.alt = slides[zoomed].querySelector("img").alt;
    lightCounter.textContent = `${zoomed + 1} / ${sources.length}`;
  };

  slides.forEach((slide, i) => slide.addEventListener("click", () => {
    zoom(i);
    lightbox.showModal();
  }));
  lightbox.querySelector("[data-lightbox-prev]")?.addEventListener("click", () => zoom(zoomed - 1));
  lightbox.querySelector("[data-lightbox-next]")?.addEventListener("click", () => zoom(zoomed + 1));
  lightbox.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight") zoom(zoomed + 1);
    if (event.key === "ArrowLeft") zoom(zoomed - 1);
  });
  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) lightbox.close();
  });
  lightbox.addEventListener("close", () => show(zoomed, false));

  let startX = null;
  lightbox.addEventListener("touchstart", (event) => { startX = event.touches[0].clientX; }, { passive: true });
  lightbox.addEventListener("touchend", (event) => {
    if (startX === null) return;
    const delta = event.changedTouches[0].clientX - startX;
    if (Math.abs(delta) > 50) zoom(zoomed + (delta < 0 ? 1 : -1));
    startX = null;
  });
}

function share(button) {
  const data = { title: button.dataset.shareTitle, url: button.dataset.shareUrl };
  if (navigator.share) {
    navigator.share(data).catch(() => {});
    return;
  }
  navigator.clipboard.writeText(data.url).then(() => {
    document.dispatchEvent(new CustomEvent("toast", { detail: { text: "Ссылка скопирована", level: "success" } }));
  });
}

export function initGallery() {
  document.querySelectorAll("[data-gallery]").forEach((root) => {
    if (root.querySelector("[data-gallery-track]")) {
      setup(root);
    }
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-share]");
    if (button) {
      share(button);
    }
  });
}
