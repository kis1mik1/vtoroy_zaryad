import { initAdForm } from "./modules/ad-form.js";
import { initAvatarInput } from "./modules/avatar-input.js";
import { initConfirm } from "./modules/confirm.js";
import { initDialogs } from "./modules/dialogs.js";
import { initDropdowns } from "./modules/dropdown.js";
import { initFilterList } from "./modules/filter-list.js";
import { initLive } from "./modules/live.js";
import { initProgress } from "./modules/progress.js";
import { initTabs } from "./modules/tabs.js";
import { initTheme } from "./modules/theme.js";
import { initToasts } from "./modules/toasts.js";
import { initUploader } from "./modules/uploader.js";

initTheme();
initDropdowns();
initDialogs();
initConfirm();
initToasts();
initTabs(document);
initFilterList();
initProgress();
initLive();
initAvatarInput();
initAdForm();
initUploader();

document.addEventListener("htmx:load", (event) => {
  initTabs(event.detail.elt);
});
