import { $ } from "../../dom.js";

export function readPageRangeInputs() {
  return {
    start: $("page-range-start")?.value || "",
    end: $("page-range-end")?.value || "",
  };
}

export function setInlinePageRangeVisible(visible) {
  $("inline-page-range")?.classList.toggle("hidden", !visible);
}

export function openPageRangeDialogView({ applied = "", maxPage = 0 } = {}) {
  const limitText = $("page-range-limit-text");
  const titleEl = $("page-range-title");
  if (maxPage > 0) {
    if (limitText) {
      limitText.textContent = "选择本次翻译使用的术语表。页码范围可直接在上传区域填写。";
    }
    if (titleEl) {
      titleEl.textContent = "专业翻译";
    }
  } else {
    if (limitText) {
      limitText.textContent = "选择本次翻译使用的术语表。页码范围可直接在上传区域填写。";
    }
    if (titleEl) {
      titleEl.textContent = "专业翻译";
    }
  }
  if (maxPage > 0) {
    $("page-range-start")?.setAttribute("max", String(maxPage));
    $("page-range-end")?.setAttribute("max", String(maxPage));
  }
  $("page-range-dialog")?.showModal();
}

export function writePageRangeInputs({ start = "", end = "" } = {}) {
  if ($("page-range-start")) {
    $("page-range-start").value = start;
  }
  if ($("page-range-end")) {
    $("page-range-end").value = end;
  }
}

export function closePageRangeDialog() {
  $("page-range-dialog")?.close();
}

export function clearPageRangeInputs() {
  writePageRangeInputs({ start: "", end: "" });
}

export function selectedUploadFile() {
  return $("file")?.files?.[0] || null;
}

export function setFileLabel(file, defaultFileLabel) {
  const label = $("file-label");
  if (!label) {
    return;
  }
  label.textContent = file ? file.name : defaultFileLabel;
  label.title = file ? file.name : "";
}

export function showUploadStatus(message) {
  const status = $("upload-status");
  if (!status) {
    return;
  }
  status.textContent = message;
  status.classList.remove("hidden");
}

export function markUploadReady(ready) {
  const tile = $("file")?.closest(".upload-tile");
  tile?.classList.toggle("is-ready", !!ready);
  tile?.classList.remove("is-uploading");
}
