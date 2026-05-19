import { openSlidePanel, showProgress, showResult } from "./panels.js";
import { apiBase, buildApiHeaders } from "../../config.js";
import { downloadPdfToolResult, getMetadata, uploadPdfToolFile } from "./api.js";

export function openMetadataPanel() {
  const panel = openSlidePanel({
    title: "元数据编辑",
    contentHtml: `
      <p class="slide-panel-desc">查看和编辑 PDF 文档信息。</p>
      <input type="file" accept=".pdf" id="meta-file-input" />
      <div id="meta-fields" class="slide-form">
        <div class="slide-config-row"><label>标题:</label><input type="text" id="meta-title" /></div>
        <div class="slide-config-row"><label>作者:</label><input type="text" id="meta-author" /></div>
        <div class="slide-config-row"><label>主题:</label><input type="text" id="meta-subject" /></div>
        <div class="slide-config-row"><label>关键词:</label><input type="text" id="meta-keywords" /></div>
      </div>
      <div class="slide-actions">
        <button id="meta-load-btn" class="button-link secondary">读取元数据</button>
        <button id="meta-save-btn" class="button-link primary disabled" disabled>保存并下载</button>
      </div>
      <div id="meta-result" class="slide-result"></div>
    `,
  });

  const fileInput = panel.overlay.querySelector("#meta-file-input");
  const loadBtn = panel.overlay.querySelector("#meta-load-btn");
  const saveBtn = panel.overlay.querySelector("#meta-save-btn");
  const titleInput = panel.overlay.querySelector("#meta-title");
  const authorInput = panel.overlay.querySelector("#meta-author");
  const subjectInput = panel.overlay.querySelector("#meta-subject");
  const keywordsInput = panel.overlay.querySelector("#meta-keywords");
  const resultDiv = panel.overlay.querySelector("#meta-result");
  let uploadedId = null;

  fileInput.onchange = async () => {
    const file = fileInput.files[0];
    if (!file) return;
    showProgress(resultDiv, "上传中...");
    try {
      const upload = await uploadPdfToolFile(file);
      uploadedId = upload.upload_id;
      loadBtn.disabled = false;
      showProgress(resultDiv, "");
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    }
  };

  loadBtn.onclick = async () => {
    if (!uploadedId) return;
    loadBtn.disabled = true;
    loadBtn.textContent = "读取中...";
    try {
      const result = await getMetadata(uploadedId);
      const m = result.data ?? result;
      titleInput.value = m.title || "";
      authorInput.value = m.author || "";
      subjectInput.value = m.subject || "";
      keywordsInput.value = m.keywords || "";
      saveBtn.disabled = false;
      saveBtn.classList.toggle("disabled", false);
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    } finally {
      loadBtn.disabled = false;
      loadBtn.textContent = "读取元数据";
    }
  };

  saveBtn.onclick = async () => {
    if (!uploadedId) return;
    saveBtn.disabled = true;
    saveBtn.textContent = "保存中...";
    try {
      const payload = { upload_id: uploadedId };
      if (titleInput.value) payload.title = titleInput.value;
      if (authorInput.value) payload.author = authorInput.value;
      if (subjectInput.value) payload.subject = subjectInput.value;
      if (keywordsInput.value) payload.keywords = keywordsInput.value;
      const res = await fetch(`${apiBase()}/api/v1/pdf-tools/metadata`, {
        method: "POST",
        headers: { ...buildApiHeaders(), "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("保存失败");
      const result = await res.json();
      if (result.code !== 0) throw new Error(result.message);
      const d = result.data;
      const resultId = d.download_url.split("/").pop();
      showResult(resultDiv, "success", "元数据已更新",
        () => downloadPdfToolResult(resultId, d.file_name || "metadata.pdf")
      );
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = "保存并下载";
    }
  };
}
