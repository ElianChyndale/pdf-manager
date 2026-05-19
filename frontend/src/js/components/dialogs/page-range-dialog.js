class PageRangeDialog extends HTMLElement {
  connectedCallback() {
    if (this.dataset.hydrated === "1") {
      return;
    }
    this.dataset.hydrated = "1";
    this.innerHTML = `
      <dialog id="page-range-dialog" class="desktop-dialog page-range-dialog professional-translate-dialog">
        <form method="dialog" class="desktop-shell">
          <div class="desktop-head">
            <h2 id="page-range-title">专业翻译</h2>
            <button id="page-range-close-btn" type="submit" class="dialog-close-btn" aria-label="关闭">×</button>
          </div>
          <div class="desktop-body">
            <p id="page-range-limit-text" class="muted">选择本次翻译使用的术语表。</p>
            <label class="professional-glossary-field">
              <span>术语表</span>
              <select id="job-glossary-id">
                <option value="">不使用术语表</option>
              </select>
            </label>
            <div class="actions">
              <button id="page-range-clear-btn" type="button" class="secondary">不使用</button>
              <button id="page-range-apply-btn" type="button">完成</button>
            </div>
          </div>
        </form>
      </dialog>
    `;
  }
}

if (!customElements.get("page-range-dialog")) {
  customElements.define("page-range-dialog", PageRangeDialog);
}
