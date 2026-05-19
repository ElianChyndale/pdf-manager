class GlossaryManagerDialog extends HTMLElement {
  connectedCallback() {
    if (this.dataset.hydrated === "1") {
      return;
    }
    this.dataset.hydrated = "1";
    this.innerHTML = `
      <dialog id="glossary-manager-dialog" class="desktop-dialog glossary-manager-dialog">
        <div class="desktop-shell glossary-manager-shell">
          <div class="desktop-head">
            <div class="credential-dialog-head">
              <h2>术语表</h2>
            </div>
            <button id="glossary-close-btn" type="button" class="dialog-close-btn" aria-label="关闭">×</button>
          </div>
          <div class="desktop-body glossary-manager-body">
            <aside class="glossary-list-panel">
              <div class="glossary-panel-head">
                <strong>列表</strong>
                <button id="glossary-new-btn" type="button" class="secondary">新建</button>
              </div>
              <div id="glossary-list" class="glossary-list"></div>
              <div id="glossary-list-empty" class="events-empty hidden">暂无术语表</div>
            </aside>

            <section class="glossary-editor-panel">
              <label class="glossary-name-field">
                <span>名称</span>
                <input id="glossary-name" type="text" autocomplete="off" placeholder="例如 量子化学术语" />
              </label>
              <div class="glossary-toolbar">
                <button id="glossary-add-row-btn" type="button" class="secondary">添加</button>
                <button id="glossary-import-btn" type="button" class="secondary">CSV</button>
                <button id="glossary-delete-btn" type="button" class="secondary danger">删除</button>
              </div>
              <div class="glossary-table-wrap">
                <table class="glossary-table">
                  <thead>
                    <tr>
                      <th class="glossary-col-source">原词</th>
                      <th class="glossary-col-target">译文</th>
                      <th class="glossary-col-level">类型</th>
                      <th class="glossary-col-match">匹配</th>
                      <th class="glossary-col-action"></th>
                    </tr>
                  </thead>
                  <tbody id="glossary-entries"></tbody>
                </table>
                <div id="glossary-entries-empty" class="events-empty">暂无词条</div>
              </div>
              <div class="glossary-import-panel hidden" id="glossary-import-panel">
                <textarea id="glossary-csv-text" rows="6" placeholder="原词,译文,类型,匹配模式"></textarea>
                <div class="glossary-import-actions">
                  <button id="glossary-import-apply-btn" type="button">解析</button>
                  <button id="glossary-import-cancel-btn" type="button" class="secondary">取消</button>
                </div>
              </div>
              <div class="glossary-footer">
                <span id="glossary-status" class="upload-status hidden"></span>
                <button id="glossary-save-btn" type="button">保存</button>
              </div>
            </section>
          </div>
        </div>
      </dialog>
    `;
  }
}

if (!customElements.get("glossary-manager-dialog")) {
  customElements.define("glossary-manager-dialog", GlossaryManagerDialog);
}
