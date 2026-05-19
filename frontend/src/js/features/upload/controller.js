import { $ } from "../../dom.js";
import { buildApiUrl } from "../../config.js";
import { setUploadState } from "../../state.js";
import {
  clearPageRangeInputs,
  closePageRangeDialog,
  markUploadReady,
  openPageRangeDialogView,
  readPageRangeInputs,
  selectedUploadFile,
  setFileLabel,
  setInlinePageRangeVisible,
  showUploadStatus,
  writePageRangeInputs,
} from "./view.js";

export function mountUploadFeature({
  state,
  apiBase,
  apiPrefix,
  frontMaxBytes,
  frontMaxPageCount,
  countPdfPages,
  defaultFileLabel,
  collectUploadFormData,
  submitUploadRequest,
  resetUploadedFile,
  resetUploadProgress,
  setUploadProgress,
  clearFileInputValue,
  setText,
  applyWorkflowMode,
  refreshSubmitControls,
  workflowNeedsUpload,
}) {
  function normalizePageRangeValue(startValue = "", endValue = "") {
    const start = startValue.trim();
    const end = endValue.trim();
    if (!start && !end) {
      return "";
    }
    if (start && end) {
      return start === end ? start : `${start}-${end}`;
    }
    return start || end;
  }

  function currentPageRanges() {
    const { start, end } = readPageRangeInputs();
    return normalizePageRangeValue(start, end);
  }

  function validatePageRanges() {
    const { start: rawStart, end: rawEnd } = readPageRangeInputs();
    const start = rawStart.trim();
    const end = rawEnd.trim();
    const maxPage = Number(state.uploadedPageCount || 0) || frontMaxPageCount;
    if ((start && Number(start) < 1) || (end && Number(end) < 1)) {
      setText("error-box", "页码必须从 1 开始");
      return false;
    }
    if ((start && maxPage && Number(start) > maxPage) || (end && maxPage && Number(end) > maxPage)) {
      setText("error-box", `页码不能超过 ${maxPage}`);
      return false;
    }
    if (start && end && Number(start) > Number(end)) {
      setText("error-box", "起始页不能大于结束页");
      return false;
    }
    if (maxPage && start && end && Number(end) - Number(start) + 1 > maxPage) {
      setText("error-box", `页码区间不能超过 ${maxPage} 页`);
      return false;
    }
    state.appliedPageRange = normalizePageRangeValue(start, end);
    return true;
  }

  function renderPageRangeSummary() {
    setInlinePageRangeVisible(workflowNeedsUpload() && Boolean(state.uploadId));
  }

  function openPageRangeDialog() {
    openPageRangeDialogView({
      applied: state.appliedPageRange || "",
      maxPage: frontMaxPageCount || 0,
    });
  }

  function applyPageRanges() {
    closePageRangeDialog();
  }

  function clearPageRanges() {
    clearPageRangeInputs();
    state.appliedPageRange = "";
    renderPageRangeSummary();
    refreshSubmitControls();
    closePageRangeDialog();
  }

  async function handleFileSelected() {
    const file = selectedUploadFile();
    resetUploadedFile();
    resetUploadProgress();
    state.appliedPageRange = "";
    clearPageRangeInputs();
    renderPageRangeSummary();
    applyWorkflowMode();
    setFileLabel(file, defaultFileLabel);
    if (!file) {
      return;
    }
    if (file.size > frontMaxBytes) {
      setText("error-box", "当前前端限制为 100MB 以内 PDF");
      showUploadStatus("文件超出大小限制");
      return;
    }
    if (frontMaxPageCount && countPdfPages) {
      showUploadStatus("正在校验页数…");
      try {
        const localPageCount = await countPdfPages(file);
        if (!Number.isFinite(localPageCount) || localPageCount <= 0) {
          setText("error-box", "PDF 解析失败，请检查文件是否损坏或可访问性异常。");
          showUploadStatus("文件校验失败");
          clearFileInputValue();
          return;
        }
        if (localPageCount > frontMaxPageCount) {
          setText("error-box", `PDF 页数超过限制：最多 ${frontMaxPageCount} 页`);
          showUploadStatus("文件超出页数限制");
          clearFileInputValue();
          return;
        }
      } catch (err) {
        setText("error-box", err?.message || "PDF 解析失败，请稍后重试。");
        showUploadStatus("文件校验失败");
        clearFileInputValue();
        return;
      }
    }
    setText("error-box", "-");
    showUploadStatus("正在上传…");

    try {
      const uploadUrl = buildApiUrl(apiPrefix, "uploads");
      const payload = await submitUploadRequest(
        uploadUrl,
        collectUploadFormData(file),
        setUploadProgress,
      );
      const uploadedPageCount = Number(payload.page_count || 0);
      if (frontMaxPageCount > 0 && uploadedPageCount > frontMaxPageCount) {
        setText("error-box", `PDF 页数超过限制：最多 ${frontMaxPageCount} 页`);
        showUploadStatus("文件超出页数限制");
        clearFileInputValue();
        resetUploadedFile();
        return;
      }
      setUploadState(state, {
        uploadId: payload.upload_id || "",
        uploadedFileName: payload.filename || file.name,
        uploadedPageCount,
        uploadedBytes: Number(payload.bytes || file.size || 0),
      });
      writePageRangeInputs({
        start: uploadedPageCount > 0 ? "1" : "",
        end: uploadedPageCount > 0 ? `${uploadedPageCount}` : "",
      });
      state.appliedPageRange = currentPageRanges();
      markUploadReady(!!state.uploadId);
      showUploadStatus("上传完成，可以开始任务。");
      clearFileInputValue();
      renderPageRangeSummary();
      refreshSubmitControls();
    } catch (err) {
      resetUploadedFile();
      clearFileInputValue();
      setText("error-box", err.message);
      showUploadStatus("上传失败");
      applyWorkflowMode();
    }
  }

  return {
    applyPageRanges,
    clearPageRanges,
    currentPageRanges,
    handleFileSelected,
    normalizePageRangeValue,
    openPageRangeDialog,
    renderPageRangeSummary,
    validatePageRanges,
  };
}
