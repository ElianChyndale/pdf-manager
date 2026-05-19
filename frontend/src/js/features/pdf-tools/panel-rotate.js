import { openSlidePanel, showProgress, showResult } from "./panels.js";
import { apiBase, buildApiHeaders } from "../../config.js";
import { downloadPdfToolResult, uploadPdfToolFile } from "./api.js";

export function openRotatePanel() {
  const panel = openSlidePanel({
    title: "旋转 PDF",
    contentHtml: `
      <p class="slide-panel-desc">旋转 PDF 页面方向。</p>
      <input type="file" accept=".pdf" id="rotate-file-input" />
      <div class="slide-config-row">
        <label>角度:</label>
        <select id="rotate-degrees">
          <option value="90">顺时针 90°</option>
          <option value="180">180°</option>
          <option value="270">逆时针 90°</option>
        </select>
      </div>
      <div class="slide-config-row">
        <label>范围:</label>
        <select id="rotate-pages">
          <option value="all">全部页面</option>
        </select>
      </div>
      <button id="rotate-execute-btn" class="button-link primary disabled" disabled>旋转</button>
      <div id="rotate-result" class="slide-result"></div>
    `,
  });

  const fileInput = panel.overlay.querySelector("#rotate-file-input");
  const degreesSelect = panel.overlay.querySelector("#rotate-degrees");
  const pagesSelect = panel.overlay.querySelector("#rotate-pages");
  const execBtn = panel.overlay.querySelector("#rotate-execute-btn");
  const resultDiv = panel.overlay.querySelector("#rotate-result");
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
    execBtn.textContent = "旋转中...";
    try {
      const degrees = parseInt(degreesSelect.value);
      const pages = pagesSelect.value;
      const res = await fetch(`${apiBase()}/api/v1/pdf-tools/rotate`, {
        method: "POST",
        headers: { ...buildApiHeaders(), "content-type": "application/json" },
        body: JSON.stringify({ upload_id: uploadedId, degrees, pages }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ message: res.statusText }));
        throw new Error(err.message || "旋转失败");
      }
      const result = await res.json();
      if (result.code !== 0) throw new Error(result.message);
      const d = result.data;
      const resultId = d.download_url.split("/").pop();
      showResult(resultDiv, "success",
        `旋转完成！共处理 ${d.details?.rotated_pages || d.page_count} 页`,
        () => downloadPdfToolResult(resultId, d.file_name || "rotated.pdf")
      );
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    } finally {
      execBtn.disabled = false;
      execBtn.textContent = "旋转";
    }
  };
}
