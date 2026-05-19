import { openSlidePanel, showResult } from "./panels.js";
import { apiBase, buildApiHeaders } from "../../config.js";
import { downloadPdfToolResult, uploadPdfToolFile } from "./api.js";

export function openMergePanel() {
  const panel = openSlidePanel({
    title: "合并 PDF",
    contentHtml: `
      <p class="slide-panel-desc">选择多个 PDF 文件，按顺序合并为一个文件。</p>
      <div class="slide-upload-area">
        <input type="file" accept=".pdf" multiple id="merge-file-input" />
        <div id="merge-file-list" class="slide-file-list"></div>
      </div>
      <button id="merge-execute-btn" class="button-link primary disabled" disabled>合并</button>
      <div id="merge-result" class="slide-result"></div>
    `,
  });

  const fileInput = panel.overlay.querySelector("#merge-file-input");
  const fileList = panel.overlay.querySelector("#merge-file-list");
  const execBtn = panel.overlay.querySelector("#merge-execute-btn");
  const resultDiv = panel.overlay.querySelector("#merge-result");
  const files = [];

  fileInput.onchange = () => {
    fileList.innerHTML = "";
    files.length = 0;
    for (const f of fileInput.files) {
      files.push(f);
      const item = document.createElement("div");
      item.className = "slide-file-item";
      item.textContent = `${f.name} (${(f.size / 1024).toFixed(0)} KB)`;
      fileList.appendChild(item);
    }
    execBtn.disabled = files.length < 2;
    execBtn.classList.toggle("disabled", files.length < 2);
  };

  execBtn.onclick = async () => {
    execBtn.disabled = true;
    execBtn.textContent = "上传中...";
    try {
      const uploadIds = [];
      for (const f of files) {
        const upload = await uploadPdfToolFile(f);
        uploadIds.push(upload.upload_id);
      }
      execBtn.textContent = "合并中...";
      const res = await fetch(`${apiBase()}/api/v1/pdf-tools/merge`, {
        method: "POST",
        headers: { ...buildApiHeaders(), "content-type": "application/json" },
        body: JSON.stringify({ upload_ids: uploadIds }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ message: res.statusText }));
        throw new Error(err.message || "合并失败");
      }
      const result = await res.json();
      if (result.code !== 0) throw new Error(result.message);
      const d = result.data;
      const resultId = d.download_url.split("/").pop();
      showResult(resultDiv, "success",
        `合并完成！共 ${d.page_count} 页，${(d.file_size / 1024 / 1024).toFixed(1)} MB`,
        () => downloadPdfToolResult(resultId, d.file_name || "merged.pdf")
      );
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    } finally {
      execBtn.disabled = false;
      execBtn.textContent = "合并";
    }
  };
}
