import { $ } from "../../dom.js";

const ENTRY_LEVEL_OPTIONS = [
  ["preserve", "保留"],
  ["canonical", "固定译法"],
  ["preferred", "偏好译法"],
];

const MATCH_MODE_OPTIONS = [
  ["case_insensitive", "忽略大小写"],
  ["exact", "精确"],
  ["regex", "正则"],
];

export function openGlossaryDialogView() {
  $("glossary-manager-dialog")?.showModal();
}

export function closeGlossaryDialogView() {
  $("glossary-manager-dialog")?.close();
}

export function setGlossaryStatus(message = "", tone = "") {
  const el = $("glossary-status");
  if (!el) {
    return;
  }
  const content = `${message || ""}`.trim();
  el.textContent = content;
  el.classList.toggle("hidden", !content);
  el.classList.toggle("is-valid", tone === "valid");
  el.classList.toggle("is-error", tone === "error");
}

export function renderGlossaryList(items = [], selectedId = "") {
  const list = $("glossary-list");
  const empty = $("glossary-list-empty");
  if (!list || !empty) {
    return;
  }
  list.textContent = "";
  const normalizedSelectedId = `${selectedId || ""}`.trim();
  empty.classList.toggle("hidden", items.length > 0);
  for (const item of items) {
    const glossaryId = `${item?.glossary_id || ""}`.trim();
    if (!glossaryId) {
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "glossary-list-item";
    button.dataset.glossaryId = glossaryId;
    button.classList.toggle("is-active", glossaryId === normalizedSelectedId);
    const name = document.createElement("strong");
    name.textContent = item.name || glossaryId;
    const meta = document.createElement("span");
    meta.textContent = `${Number(item.entry_count) || 0} 条`;
    button.append(name, meta);
    list.append(button);
  }
}

function buildOption(value, label, selectedValue) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  option.selected = value === selectedValue;
  return option;
}

function createSelect(options, selectedValue, className) {
  const select = document.createElement("select");
  select.className = className;
  for (const [value, label] of options) {
    select.append(buildOption(value, label, selectedValue));
  }
  return select;
}

function createTextInput(value, className, placeholder = "") {
  const input = document.createElement("input");
  input.type = "text";
  input.className = className;
  input.value = `${value || ""}`;
  input.placeholder = placeholder;
  return input;
}

export function renderGlossaryEditor({ name = "", entries = [] } = {}) {
  const nameInput = $("glossary-name");
  const tbody = $("glossary-entries");
  const empty = $("glossary-entries-empty");
  if (nameInput) {
    nameInput.value = name;
  }
  if (!tbody || !empty) {
    return;
  }
  tbody.textContent = "";
  empty.classList.toggle("hidden", entries.length > 0);
  for (const entry of entries) {
    appendGlossaryEntryRow(entry);
  }
}

export function appendGlossaryEntryRow(entry = {}) {
  const tbody = $("glossary-entries");
  const empty = $("glossary-entries-empty");
  if (!tbody) {
    return;
  }
  const tr = document.createElement("tr");
  tr.className = "glossary-entry-row";

  const sourceCell = document.createElement("td");
  sourceCell.append(createTextInput(entry.source, "glossary-entry-source", "Hartree-Fock"));

  const targetCell = document.createElement("td");
  targetCell.append(createTextInput(entry.target, "glossary-entry-target", "可留空"));

  const levelCell = document.createElement("td");
  levelCell.append(createSelect(ENTRY_LEVEL_OPTIONS, entry.level || "preserve", "glossary-entry-level"));

  const matchCell = document.createElement("td");
  matchCell.append(createSelect(MATCH_MODE_OPTIONS, entry.match_mode || "case_insensitive", "glossary-entry-match"));

  const actionCell = document.createElement("td");
  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "glossary-entry-remove secondary";
  removeButton.setAttribute("aria-label", "删除词条");
  removeButton.textContent = "×";
  actionCell.append(removeButton);

  tr.append(sourceCell, targetCell, levelCell, matchCell, actionCell);
  tbody.append(tr);
  empty?.classList.add("hidden");
}

export function readGlossaryEditorPayload() {
  const entries = [];
  const skippedMissingTarget = [];
  $("glossary-entries")?.querySelectorAll(".glossary-entry-row").forEach((row) => {
    const source = row.querySelector(".glossary-entry-source")?.value?.trim() || "";
    if (!source) {
      return;
    }
    const level = row.querySelector(".glossary-entry-level")?.value || "preserve";
    const typedTarget = row.querySelector(".glossary-entry-target")?.value?.trim() || "";
    const target = typedTarget || (level === "preserve" ? source : "");
    if (!target) {
      skippedMissingTarget.push(source);
      return;
    }
    entries.push({
      source,
      target,
      level,
      match_mode: row.querySelector(".glossary-entry-match")?.value || "case_insensitive",
      context: "",
      note: "",
    });
  });
  return {
    name: $("glossary-name")?.value?.trim() || "未命名术语表",
    entries,
    skippedMissingTarget,
  };
}

export function setGlossaryImportVisible(visible) {
  $("glossary-import-panel")?.classList.toggle("hidden", !visible);
}

export function readGlossaryCsvText() {
  return $("glossary-csv-text")?.value || "";
}

export function clearGlossaryCsvText() {
  if ($("glossary-csv-text")) {
    $("glossary-csv-text").value = "";
  }
}

export function bindGlossaryViewEvents({
  open,
  close,
  reload,
  selectGlossary,
  createNew,
  addRow,
  save,
  deleteCurrent,
  showImport,
  hideImport,
  applyImport,
}) {
  $("glossary-btn")?.addEventListener("click", open);
  $("glossary-close-btn")?.addEventListener("click", close);
  $("glossary-new-btn")?.addEventListener("click", createNew);
  $("glossary-add-row-btn")?.addEventListener("click", addRow);
  $("glossary-save-btn")?.addEventListener("click", save);
  $("glossary-delete-btn")?.addEventListener("click", deleteCurrent);
  $("glossary-import-btn")?.addEventListener("click", showImport);
  $("glossary-import-cancel-btn")?.addEventListener("click", hideImport);
  $("glossary-import-apply-btn")?.addEventListener("click", applyImport);
  $("glossary-list")?.addEventListener("click", (event) => {
    const button = event.target?.closest?.(".glossary-list-item");
    if (button?.dataset.glossaryId) {
      selectGlossary(button.dataset.glossaryId);
    }
  });
  $("glossary-entries")?.addEventListener("click", (event) => {
    const button = event.target?.closest?.(".glossary-entry-remove");
    if (!button) {
      return;
    }
    button.closest(".glossary-entry-row")?.remove();
    const hasRows = Boolean($("glossary-entries")?.querySelector(".glossary-entry-row"));
    $("glossary-entries-empty")?.classList.toggle("hidden", hasRows);
  });
  document.addEventListener("pdf-manager:refresh-glossaries", () => reload?.());
}
