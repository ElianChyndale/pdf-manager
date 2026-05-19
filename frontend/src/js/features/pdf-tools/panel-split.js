import { openSlidePanel, showProgress, showResult } from "./panels.js";
import { apiBase, buildApiHeaders } from "../../config.js";
import { uploadPdfToolFile } from "./api.js";

export function openSplitPanel() {
  const panel = openSlidePanel({
    title: "拆分 PDF",
    contentHtml: `
      <p class="slide-panel-desc">选择一个 PDF 并按页码范围拆分为多个文件。</p>
      <input type="file" accept=".pdf" id="split-file-input" />
      <div id="split-range-list">
        <div class="split-range-row">
          <label>范围 1:</label>
          <input type="number" class="split-start" min="1" placeholder="起始页" />
          <span>-</span>
          <input type="number" class="split-end" min="1" placeholder="结束页" />
          <button class="split-remove-btn hidden">&times;</button>
        </div>
      </div>
      <button id="split-add-range" class="button-link secondary">+ 添加范围</button>
      <button id="split-execute-btn" class="button-link primary disabled" disabled>拆分</button>
      <div id="split-result" class="slide-result"></div>
    `,
  });

  const fileInput = panel.overlay.querySelector("#split-file-input");
  const rangeList = panel.overlay.querySelector("#split-range-list");
  const addBtn = panel.overlay.querySelector("#split-add-range");
  const execBtn = panel.overlay.querySelector("#split-execute-btn");
  const resultDiv = panel.overlay.querySelector("#split-result");
  let uploadedId = null;

  function updateRows() {
    const rows = rangeList.querySelectorAll(".split-range-row");
    rows.forEach((row, i) => {
      const label = row.querySelector("label");
      if (label) label.textContent = `范围 ${i + 1}:`;
      const removeBtn = row.querySelector(".split-remove-btn");
      if (removeBtn) removeBtn.classList.toggle("hidden", rows.length <= 1);
    });
    execBtn.disabled = !uploadedId;
    execBtn.classList.toggle("disabled", !uploadedId);
  }

  addBtn.onclick = () => {
    const row = document.createElement("div");
    row.className = "split-range-row";
    row.innerHTML = `
      <label>范围 ${rangeList.children.length + 1}:</label>
      <input type="number" class="split-start" min="1" placeholder="起始页" />
      <span>-</span>
      <input type="number" class="split-end" min="1" placeholder="结束页" />
      <button class="split-remove-btn">&times;</button>
    `;
    row.querySelector(".split-remove-btn").onclick = () => {
      row.remove();
      updateRows();
    };
    rangeList.appendChild(row);
    updateRows();
  };

  fileInput.onchange = async () => {
    const file = fileInput.files[0];
    if (!file) return;
    showProgress(resultDiv, "上传中...");
    try {
      const upload = await uploadPdfToolFile(file);
      uploadedId = upload.upload_id;
      updateRows();
      showProgress(resultDiv, "");
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    }
  };

  execBtn.onclick = async () => {
    if (!uploadedId) return;
    execBtn.disabled = true;
    execBtn.textContent = "拆分中...";
    try {
      const ranges = [];
      rangeList.querySelectorAll(".split-range-row").forEach((row) => {
        const start = row.querySelector(".split-start").value;
        const end = row.querySelector(".split-end").value;
        if (start && end) {
          ranges.push({ start: parseInt(start), end: parseInt(end), label: `p${start}-${end}` });
        }
      });
      if (ranges.length === 0) throw new Error("请至少填写一个页码范围");
      const res = await fetch(`${apiBase()}/api/v1/pdf-tools/split`, {
        method: "POST",
        headers: { ...buildApiHeaders(), "content-type": "application/json" },
        body: JSON.stringify({ upload_id: uploadedId, ranges }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ message: res.statusText }));
        throw new Error(err.message || "拆分失败");
      }
      const result = await res.json();
      if (result.code !== 0) throw new Error(result.message);
      const items = result.data;
      showResult(resultDiv, "success", `拆分完成！共 ${items.length} 个文件`);
      // Show individual file links
      const linkList = document.createElement("div");
      linkList.className = "slide-result-links";
      items.forEach((item, i) => {
        const link = document.createElement("a");
        link.href = "#";
        link.className = "button-link secondary";
        link.textContent = `下载 ${item.label || `部分 ${i + 1}`}`;
        link.onclick = () => {
          // For split results, each item contains a 'details' field with the file
          alert("拆分结果已保存到服务端临时目录，请联系管理员获取文件。");
        };
        linkList.appendChild(link);
      });
      resultDiv.appendChild(linkList);
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    } finally {
      execBtn.disabled = false;
      execBtn.textContent = "拆分";
    }
  };
}
