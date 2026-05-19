import { openSlidePanel, showProgress, showResult } from "./panels.js";
import { apiBase, buildApiHeaders } from "../../config.js";
import { downloadPdfToolResult, uploadPdfToolFile } from "./api.js";

export function openEncryptPanel() {
  const panel = openSlidePanel({
    title: "加密 / 解密 PDF",
    contentHtml: `
      <p class="slide-panel-desc">为 PDF 添加密码保护，或移除密码。</p>
      <input type="file" accept=".pdf" id="encrypt-file-input" />
      <div class="slide-tabs">
        <button class="slide-tab active" data-tab="encrypt">加密</button>
        <button class="slide-tab" data-tab="decrypt">解密</button>
      </div>
      <div id="encrypt-tab-content">
        <div class="slide-config-row"><label>打开密码:</label><input type="password" id="encrypt-user-pw" /></div>
        <div class="slide-config-row"><label>所有者密码:</label><input type="password" id="encrypt-owner-pw" /></div>
      </div>
      <div id="decrypt-tab-content" class="hidden">
        <div class="slide-config-row"><label>密码:</label><input type="password" id="decrypt-pw" /></div>
      </div>
      <button id="encrypt-execute-btn" class="button-link primary disabled" disabled>执行</button>
      <div id="encrypt-result" class="slide-result"></div>
    `,
  });

  const fileInput = panel.overlay.querySelector("#encrypt-file-input");
  const encryptTab = panel.overlay.querySelector("#encrypt-tab-content");
  const decryptTab = panel.overlay.querySelector("#decrypt-tab-content");
  const encryptTabBtn = panel.overlay.querySelector('[data-tab="encrypt"]');
  const decryptTabBtn = panel.overlay.querySelector('[data-tab="decrypt"]');
  const userPw = panel.overlay.querySelector("#encrypt-user-pw");
  const ownerPw = panel.overlay.querySelector("#encrypt-owner-pw");
  const decryptPw = panel.overlay.querySelector("#decrypt-pw");
  const execBtn = panel.overlay.querySelector("#encrypt-execute-btn");
  const resultDiv = panel.overlay.querySelector("#encrypt-result");
  let uploadedId = null;
  let mode = "encrypt";

  encryptTabBtn.onclick = () => {
    mode = "encrypt";
    encryptTabBtn.classList.add("active");
    decryptTabBtn.classList.remove("active");
    encryptTab.classList.remove("hidden");
    decryptTab.classList.add("hidden");
  };
  decryptTabBtn.onclick = () => {
    mode = "decrypt";
    decryptTabBtn.classList.add("active");
    encryptTabBtn.classList.remove("active");
    decryptTab.classList.remove("hidden");
    encryptTab.classList.add("hidden");
  };

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
    execBtn.textContent = "处理中...";
    try {
      let url, payload;
      if (mode === "encrypt") {
        url = `${apiBase()}/api/v1/pdf-tools/encrypt`;
        payload = { upload_id: uploadedId, user_password: userPw.value || null, owner_password: ownerPw.value || null };
      } else {
        url = `${apiBase()}/api/v1/pdf-tools/decrypt`;
        payload = { upload_id: uploadedId, password: decryptPw.value };
      }
      const res = await fetch(url, {
        method: "POST",
        headers: { ...buildApiHeaders(), "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ message: res.statusText }));
        throw new Error(err.message || "处理失败");
      }
      const result = await res.json();
      if (result.code !== 0) throw new Error(result.message);
      const d = result.data;
      const label = mode === "encrypt" ? "加密" : "解密";
      const resultId = d.download_url.split("/").pop();
      showResult(resultDiv, "success", `${label}完成！${d.page_count} 页`,
        () => downloadPdfToolResult(resultId, d.file_name || `${mode}.pdf`)
      );
    } catch (err) {
      showResult(resultDiv, "error", err.message);
    } finally {
      execBtn.disabled = false;
      execBtn.textContent = "执行";
    }
  };
}
