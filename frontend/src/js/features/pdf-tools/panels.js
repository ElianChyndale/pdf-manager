import { $ } from "../../dom.js";

export function openSlidePanel({ title, contentHtml, onClose }) {
  const overlayId = "slide-overlay-" + Date.now();
  const overlay = document.createElement("div");
  overlay.id = overlayId;
  overlay.className = "slide-overlay";
  overlay.innerHTML = `
    <div class="slide-panel" role="dialog" aria-modal="true" aria-label="${title}">
      <div class="slide-panel-header">
        <h3>${title}</h3>
        <button class="slide-panel-close" aria-label="关闭">&times;</button>
      </div>
      <div class="slide-panel-body">${contentHtml}</div>
    </div>
  `;

  const close = () => {
    overlay.classList.remove("active");
    setTimeout(() => overlay.remove(), 300);
    onClose?.();
  };

  overlay.querySelector(".slide-panel-close").onclick = close;
  overlay.onclick = (e) => { if (e.target === overlay) close(); };
  document.addEventListener("keydown", function handler(ev) {
    if (ev.key === "Escape") { close(); document.removeEventListener("keydown", handler); }
  });
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("active"));
  return { overlay, close };
}

export function showProgress(container, text) {
  let bar = container.querySelector(".progress-bar-container");
  if (!bar) {
    bar = document.createElement("div");
    bar.className = "progress-bar-container";
    bar.innerHTML = '<div class="progress-bar"><span class="progress-fill"></span><span class="progress-text"></span></div>';
    container.appendChild(bar);
  }
  bar.querySelector(".progress-text").textContent = text || "";
}

export function showResult(container, type, message, downloadAction) {
  if (type === "success" && downloadAction) {
    container.innerHTML = `
      <div class="slide-result-success">
        <p>✅ ${message}</p>
        <button type="button" class="button-link primary slide-result-download">下载</button>
      </div>
    `;
    const button = container.querySelector(".slide-result-download");
    if (button && typeof downloadAction === "function") {
      button.onclick = downloadAction;
    }
  } else if (type === "success") {
    container.innerHTML = `<div class="slide-result-success"><p>✅ ${message}</p></div>`;
  } else if (type === "error") {
    container.innerHTML = `<p class="slide-result-error">❌ ${message}</p>`;
  } else {
    container.innerHTML = "";
  }
}
