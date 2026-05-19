import {
  appendGlossaryEntryRow,
  bindGlossaryViewEvents,
  clearGlossaryCsvText,
  closeGlossaryDialogView,
  openGlossaryDialogView,
  readGlossaryCsvText,
  readGlossaryEditorPayload,
  renderGlossaryEditor,
  renderGlossaryList,
  setGlossaryImportVisible,
  setGlossaryStatus,
} from "./view.js";

export function mountGlossariesFeature({
  apiPrefix,
  fetchGlossaries,
  fetchGlossary,
  createGlossary,
  updateGlossary,
  deleteGlossary,
  parseGlossaryCsv,
  refreshWorkflowGlossaries,
}) {
  const state = {
    items: [],
    selectedId: "",
    currentDetail: null,
    draftOnly: false,
  };

  function renderList() {
    renderGlossaryList(state.items, state.selectedId);
  }

  function renderDraft(detail = {}) {
    state.currentDetail = {
      glossary_id: detail.glossary_id || "",
      name: detail.name || "",
      entries: Array.isArray(detail.entries) ? detail.entries : [],
    };
    renderGlossaryEditor(state.currentDetail);
  }

  async function reloadGlossaries({ keepSelection = true } = {}) {
    const payload = await fetchGlossaries(apiPrefix);
    state.items = Array.isArray(payload?.items) ? payload.items : [];
    if (!keepSelection || !state.items.some((item) => item.glossary_id === state.selectedId)) {
      state.selectedId = state.items[0]?.glossary_id || "";
    }
    renderList();
    if (state.selectedId) {
      await selectGlossary(state.selectedId);
    } else {
      state.draftOnly = true;
      renderDraft({ name: "", entries: [] });
    }
    return state.items;
  }

  async function selectGlossary(glossaryId) {
    const normalizedGlossaryId = `${glossaryId || ""}`.trim();
    if (!normalizedGlossaryId) {
      return;
    }
    state.selectedId = normalizedGlossaryId;
    state.draftOnly = false;
    renderList();
    setGlossaryStatus("正在读取术语表...");
    try {
      const detail = await fetchGlossary(normalizedGlossaryId, apiPrefix);
      renderDraft(detail);
      setGlossaryStatus("");
    } catch (err) {
      setGlossaryStatus(err.message || String(err), "error");
    }
  }

  async function open() {
    openGlossaryDialogView();
    setGlossaryStatus("正在读取术语表...");
    try {
      await reloadGlossaries();
      setGlossaryStatus("");
    } catch (err) {
      setGlossaryStatus(err.message || String(err), "error");
    }
  }

  function close() {
    closeGlossaryDialogView();
  }

  function createNew() {
    state.selectedId = "";
    state.draftOnly = true;
    renderList();
    renderDraft({
      name: "未命名术语表",
      entries: [],
    });
    appendGlossaryEntryRow();
    setGlossaryStatus("新术语表尚未保存。");
  }

  async function save() {
    const payload = readGlossaryEditorPayload();
    if (!payload.name.trim()) {
      setGlossaryStatus("请填写术语表名称。", "error");
      return;
    }
    if (payload.skippedMissingTarget?.length > 0) {
      setGlossaryStatus("固定译法/偏好译法需要填写译文。", "error");
      return;
    }
    delete payload.skippedMissingTarget;
    setGlossaryStatus("正在保存...");
    try {
      const saved = state.selectedId && !state.draftOnly
        ? await updateGlossary(apiPrefix, state.selectedId, payload)
        : await createGlossary(apiPrefix, payload);
      state.selectedId = saved.glossary_id || state.selectedId;
      state.draftOnly = false;
      await reloadGlossaries();
      await refreshWorkflowGlossaries?.({ force: true, selectedId: state.selectedId });
      const select = document.getElementById("developer-glossary-id");
      if (select && state.selectedId) {
        select.value = state.selectedId;
      }
      setGlossaryStatus("已保存。", "valid");
    } catch (err) {
      setGlossaryStatus(err.message || String(err), "error");
    }
  }

  async function deleteCurrent() {
    if (!state.selectedId || state.draftOnly) {
      renderDraft({ name: "", entries: [] });
      state.draftOnly = false;
      setGlossaryStatus("");
      return;
    }
    setGlossaryStatus("正在删除...");
    try {
      await deleteGlossary(apiPrefix, state.selectedId);
      state.selectedId = "";
      await reloadGlossaries({ keepSelection: false });
      await refreshWorkflowGlossaries?.({ force: true, selectedId: "" });
      setGlossaryStatus("已删除。", "valid");
    } catch (err) {
      setGlossaryStatus(err.message || String(err), "error");
    }
  }

  async function applyImport() {
    const csvText = readGlossaryCsvText();
    if (!csvText.trim()) {
      setGlossaryStatus("请先粘贴 CSV 内容。", "error");
      return;
    }
    setGlossaryStatus("正在解析 CSV...");
    try {
      const payload = await parseGlossaryCsv(apiPrefix, csvText);
      renderDraft({
        ...readGlossaryEditorPayload(),
        entries: Array.isArray(payload?.entries) ? payload.entries : [],
      });
      clearGlossaryCsvText();
      setGlossaryImportVisible(false);
      setGlossaryStatus(`已解析 ${Number(payload?.entry_count) || 0} 条。`, "valid");
    } catch (err) {
      setGlossaryStatus(err.message || String(err), "error");
    }
  }

  function bindEvents() {
    bindGlossaryViewEvents({
      open,
      close,
      reload: () => reloadGlossaries().catch((err) => setGlossaryStatus(err.message || String(err), "error")),
      selectGlossary,
      createNew,
      addRow: () => appendGlossaryEntryRow(),
      save,
      deleteCurrent,
      showImport: () => setGlossaryImportVisible(true),
      hideImport: () => setGlossaryImportVisible(false),
      applyImport,
    });
  }

  return {
    bindEvents,
    open,
    reloadGlossaries,
  };
}
