import { postForm } from "./chat.js";
import { showToast } from "./toasts.js";

const LIMIT_SECONDS = 120;
const TYPES = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"];

function formatTime(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

export function initVoiceRecorder(root, list) {
  const start = root.querySelector("[data-voice-start]");
  if (!start) {
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    start.hidden = true;
    return;
  }
  const form = root.querySelector("[data-chat-form]");
  const panel = root.querySelector("[data-voice-panel]");
  const timer = panel.querySelector("[data-voice-timer]");
  let recorder = null;
  let cancelled = false;

  const toggle = (recording) => {
    panel.hidden = !recording;
    form.hidden = recording;
  };

  start.addEventListener("click", async () => {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      showToast("Нет доступа к микрофону. Разрешите его в настройках браузера.", "error");
      return;
    }
    const mimeType = TYPES.find((type) => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    const startedAt = Date.now();
    cancelled = false;
    const tick = setInterval(() => {
      const seconds = (Date.now() - startedAt) / 1000;
      timer.textContent = formatTime(seconds);
      if (seconds >= LIMIT_SECONDS) {
        recorder.stop();
      }
    }, 250);

    recorder.addEventListener("dataavailable", (event) => chunks.push(event.data));
    recorder.addEventListener("stop", async () => {
      clearInterval(tick);
      stream.getTracks().forEach((track) => track.stop());
      toggle(false);
      timer.textContent = "0:00";
      if (cancelled || !chunks.length) {
        return;
      }
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      const data = new FormData();
      data.append("voice", blob, "voice");
      const pending = document.createElement("li");
      pending.className = "msg msg--mine msg--pending";
      pending.dataset.voicePending = "";
      pending.innerHTML = '<div class="msg__bubble"><p class="msg__text">Голосовое обрабатывается…</p></div>';
      list.append(pending);
      list.scrollTop = list.scrollHeight;
      if ((await postForm(start.dataset.url, data)) === null) {
        pending.remove();
      }
    });
    recorder.start();
    toggle(true);
  });

  panel.querySelector("[data-voice-cancel]").addEventListener("click", () => {
    cancelled = true;
    recorder?.stop();
  });
  panel.querySelector("[data-voice-send]").addEventListener("click", () => recorder?.stop());
}

export function initVoicePlayers() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest(".voice__play");
    if (!button) {
      return;
    }
    const player = button.closest("[data-voice-player]");
    const audio = player.querySelector("audio");
    const bar = player.querySelector("[data-voice-bar]");
    const time = player.querySelector("[data-voice-time]");
    const icon = button.querySelector("use");
    if (!player.dataset.ready) {
      player.dataset.ready = "true";
      audio.addEventListener("timeupdate", () => {
        bar.style.width = `${(audio.currentTime / (audio.duration || 1)) * 100}%`;
        time.textContent = formatTime(audio.currentTime);
      });
      audio.addEventListener("ended", () => {
        bar.style.width = "0";
        time.textContent = time.dataset.total;
        icon.setAttribute("href", icon.getAttribute("href").replace("#pause", "#play"));
      });
    }
    document.querySelectorAll("[data-voice-player] audio").forEach((other) => {
      if (other !== audio && !other.paused) {
        other.pause();
        const otherIcon = other.closest("[data-voice-player]").querySelector(".voice__play use");
        otherIcon.setAttribute("href", otherIcon.getAttribute("href").replace("#pause", "#play"));
      }
    });
    if (audio.paused) {
      audio.play();
      icon.setAttribute("href", icon.getAttribute("href").replace("#play", "#pause"));
    } else {
      audio.pause();
      icon.setAttribute("href", icon.getAttribute("href").replace("#pause", "#play"));
    }
  });
}
