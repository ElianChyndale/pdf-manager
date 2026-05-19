import { openSlidePanel, showProgress, showResult } from "./panels.js";
import { apiBase, buildApiHeaders } from "../../config.js";
import { downloadPdfToolResult, uploadPdfToolFile } from "./api.js";

export function openCompressPanel() {
  const panel = openSlidePanel({
    title: "压缩 PDF",
    contentHtml: `
      <p class="slide-panel-desc">压缩 PDF 中的图片来减小文件体积。</p>
      <input type="file" accept=".pdf" id="compress-file-input" />
      <div class="slide-config-row">
        <label>目标 DPI:</label>
        <select id="compress-dpi">
          <option value="72">72 DPI (最小体积)</option>
          <option value="96">96 DPI (屏幕阅读)</option>
          <option value="150" selected>150 DPI (推荐)</option>
          <option value="200">200 DPI (高质量)</option>
          <option value="300">300 DPI (印刷级)</option>
        </select>
      </div>
      <button id="compress-execute-btn" class="button-link primary disabled" disabled>压缩</button>
      <div id="compress-result" class="slide-result"></div>
    `,
  });

  const fileInput = panel.overlay.querySelector("#compress-file-input");
  const dpiSelect = panel.overlay.querySelector("#compress-dpi");
  const execBtn = panel.overlay.querySelector("#compress-execute-btn");
  const resultDiv = panel.overlay.querySelector("#compress-result");
  let uploadedId = null;

  fileInput.onchange = async () => {
    const file = fileInput.files[0];
    if (!file) return;
    showProgress(resultDiv, "上传中...");
    try {
      const upload = await uploadPdfToolFile(file);
      uploadedId = upload.upload_id;
      execBtn.disabled = false;
      execBtn.classList.toggle("disabled", false);
      showProgress(resultDiv, "");
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    }
  };

  execBtn.onclick = async () => {
    if (!uploadedId) return;
    execBtn.disabled = true;
    execBtn.textContent = "压缩中...";
    try {
      const dpi = parseInt(dpiSelect.value);
      const res = await fetch(`${apiBase()}/api/v1/pdf-tools/compress`, {
        method: "POST",
        headers: { ...buildApiHeaders(), "content-type": "application/json" },
        body: JSON.stringify({ upload_id: uploadedId, dpi }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ message: res.statusText }));
        throw new Error(err.message || "压缩失败");
      }
      const result = await res.json();
      if (result.code !== 0) throw new Error(result.message);
      const d = result.data;
      const savedMb = ((d.details?.original_size || 0) - d.file_size) / 1024 / 1024;
      const resultId = d.download_url.split("/").pop();
      showResult(resultDiv, "success",
        `压缩完成！${(d.file_size / 1024 / 1024).toFixed(1)} MB (节省 ${savedMb.toFixed(1)} MB)`,
        () => downloadPdfToolResult(resultId, d.file_name || "compressed.pdf")
      );
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    } finally {
      execBtn.disabled = false;
      execBtn.textContent = "压缩";
    }
  };
}
