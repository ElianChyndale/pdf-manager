import { apiBase as getApiBase, buildApiHeaders } from "../../config.js";
import { submitUploadRequest } from "../../network.js";

async function postTool(action, payload) {
  const url = `${getApiBase()}/api/v1/pdf-tools/${action}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { ...buildApiHeaders(), "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(err.message || `请求失败: ${res.status}`);
  }
  return res.json();
}

async function getTool(action, payload) {
  const url = new URL(`${getApiBase()}/api/v1/pdf-tools/${action}`);
  for (const [key, value] of Object.entries(payload || {})) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    url.searchParams.set(key, `${value}`);
  }
  const res = await fetch(url, {
    method: "GET",
    headers: buildApiHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(err.message || `请求失败: ${res.status}`);
  }
  return res.json();
}

export async function uploadPdfToolFile(file, onProgress) {
  const formData = new FormData();
  formData.append("file", file);
  return submitUploadRequest(
    `${getApiBase()}/api/v1/uploads`,
    formData,
    onProgress,
  );
}

export async function mergePdfs(uploadIds) {
  return postTool("merge", { upload_ids: uploadIds });
}

export async function splitPdf(uploadId, ranges) {
  return postTool("split", { upload_id: uploadId, ranges });
}

export async function compressPdf(uploadId, dpi = 150) {
  return postTool("compress", { upload_id: uploadId, dpi });
}

export async function rotatePdf(uploadId, degrees = 90, pages = "all") {
  return postTool("rotate", { upload_id: uploadId, degrees, pages });
}

export async function getMetadata(uploadId) {
  return getTool("metadata", { upload_id: uploadId });
}

export async function updateMetadata(uploadId, fields) {
  return postTool("metadata", { upload_id: uploadId, ...fields });
}

export async function encryptPdf(uploadId, userPassword, ownerPassword) {
  return postTool("encrypt", { upload_id: uploadId, user_password: userPassword, owner_password: ownerPassword });
}

export async function decryptPdf(uploadId, password) {
  return postTool("decrypt", { upload_id: uploadId, password });
}

export function getResultDownloadUrl(apiBaseUrl, resultId) {
  return `${apiBaseUrl}/api/v1/pdf-tools/result/${resultId}`;
}

export async function downloadPdfToolResult(resultId, fileName = "result.pdf") {
  const url = getResultDownloadUrl(getApiBase(), resultId);
  const res = await fetch(url, {
    method: "GET",
    headers: buildApiHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(err.message || `下载失败: ${res.status}`);
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
