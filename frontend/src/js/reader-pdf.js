import * as pdfjsLib from "../../vendor/pdfjs-dist/build/pdf.mjs";
import { apiBase, buildApiHeaders } from "./config.js";
import { $ } from "./dom.js";
import {
  showReaderPaneEmpty,
  showReaderPaneReady,
} from "./reader-view.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "../../vendor/pdfjs-dist/build/pdf.worker.mjs",
  import.meta.url,
).toString();

const PDFJS_CMAP_URL = new URL("../../vendor/pdfjs-dist/cmaps/", import.meta.url).toString();
const PDFJS_STANDARD_FONT_DATA_URL = new URL("../../vendor/pdfjs-dist/standard_fonts/", import.meta.url).toString();
const MAX_READER_CANVAS_PIXELS = 8192 * 8192;
const READER_RANGE_CHUNK_SIZE = 512 * 1024;
const MAX_READER_OUTPUT_SCALE = 2.5;

const viewerControllers = new Map();
let resizeTicking = false;
let pageRowSyncTicking = false;
let regionOverlayTicking = false;
let readerRegionBinding = null;
let selectedReaderRegion = null;
let hoveredReaderRegion = null;
const readerRegionItemCache = new Map();

export function resolveReaderArtifactUrl(item) {
  const raw = `${item?.resource_url || item?.resource_path || ""}`.trim();
  if (!raw) {
    return "";
  }
  if (/^https?:\/\//i.test(raw)) {
    return raw;
  }
  if (raw.startsWith("/")) {
    return `${apiBase()}${raw}`;
  }
  return `${apiBase()}/${raw.replace(/^\.?\//, "")}`;
}

function getViewerController(key) {
  return viewerControllers.get(key) || null;
}

function applyViewerScale(controller) {
  if (!controller?.pdfDocument || !controller.basePageWidth) {
    return;
  }
  const hostWidth = Math.max(320, controller.viewerHost.clientWidth || 0);
  const availableWidth = Math.max(280, hostWidth - 12);
  const scale = Math.max(0.35, Math.min(2.4, availableWidth / controller.basePageWidth));
  if (Math.abs((controller.currentScale || 0) - scale) < 0.005) {
    return;
  }
  controller.currentScale = scale;
  updateManualPageSizes(controller);
  controller.renderTasks?.forEach((task) => task?.cancel?.());
  controller.renderTasks?.clear();
  controller.renderedPages?.clear();
  scheduleVisibleManualPages(controller);
  schedulePageRowSync();
}

function resetSyncedPageHeights() {
  viewerControllers.forEach((controller) => {
    controller.viewerElement.querySelectorAll(".page").forEach((page) => {
      page.style.minHeight = "";
    });
  });
}

function syncReaderPageRows() {
  const rows = new Map();
  resetSyncedPageHeights();
  viewerControllers.forEach((controller) => {
    controller.viewerElement.querySelectorAll(".page[data-page-number]").forEach((page) => {
      const pageNumber = page.getAttribute("data-page-number") || "";
      if (!pageNumber) {
        return;
      }
      const height = page.getBoundingClientRect().height;
      if (!Number.isFinite(height) || height <= 0) {
        return;
      }
      const row = rows.get(pageNumber) || { height: 0, pages: [] };
      row.height = Math.max(row.height, height);
      row.pages.push(page);
      rows.set(pageNumber, row);
    });
  });
  rows.forEach((row) => {
    if (row.pages.length < 2 || row.height <= 0) {
      return;
    }
    const height = `${Math.ceil(row.height)}px`;
    row.pages.forEach((page) => {
      page.style.minHeight = height;
    });
  });
}

function schedulePageRowSync() {
  if (pageRowSyncTicking) {
    return;
  }
  pageRowSyncTicking = true;
  window.requestAnimationFrame(() => {
    pageRowSyncTicking = false;
    syncReaderPageRows();
  });
}

function pageNumberOfElement(pageElement) {
  return Number(pageElement?.getAttribute?.("data-page-number") || 0);
}

function getPageCanvasBox(pageElement) {
  const canvas = pageElement?.querySelector?.("canvas");
  const pageRect = pageElement?.getBoundingClientRect?.();
  const rect = canvas?.getBoundingClientRect?.();
  if (!rect || !pageRect || rect.width <= 0 || rect.height <= 0) {
    return null;
  }
  return {
    left: rect.left - pageRect.left,
    top: rect.top - pageRect.top,
    width: rect.width,
    height: rect.height,
    pdfWidth: 0,
    pdfHeight: 0,
  };
}

function getPdfPageView(controller, pageNumber) {
  const viewport = controller?.pageViewports?.get(Number(pageNumber));
  if (!viewport) {
    return null;
  }
  return {
    pdfPage: {
      getViewport: ({ scale = 1 } = {}) => ({
        width: viewport.width * scale,
        height: viewport.height * scale,
      }),
    },
  };
}

function getPageCanvasBoxWithPdfSize(controller, pageElement, pageNumber) {
  const canvasBox = getPageCanvasBox(pageElement);
  const pageView = getPdfPageView(controller, pageNumber);
  const viewport = pageView?.pdfPage?.getViewport?.({ scale: 1 });
  if (!canvasBox || !viewport?.width || !viewport?.height) {
    return canvasBox;
  }
  return {
    ...canvasBox,
    pdfWidth: viewport.width,
    pdfHeight: viewport.height,
  };
}

function ensureRegionLayer(pageElement, className) {
  let layer = pageElement.querySelector(`.${className}`);
  if (!layer) {
    layer = document.createElement("div");
    layer.className = className;
    pageElement.appendChild(layer);
  }
  return layer;
}

function clearRegionLayers(controller, className) {
  controller?.viewerElement.querySelectorAll(`.${className}`).forEach((layer) => {
    layer.innerHTML = "";
  });
}

function normalizeReaderRegions(regions) {
  return (Array.isArray(regions) ? regions : [])
    .map((region) => {
      const sourcePage = Number(region?.source?.page || 0);
      const translatedPage = Number(region?.translated?.page || 0);
      const sourceBox = Array.isArray(region?.source?.bbox) ? region.source.bbox.map(Number) : [];
      const translatedBox = Array.isArray(region?.translated?.bbox) ? region.translated.bbox.map(Number) : [];
      if (
        !sourcePage
        || !translatedPage
        || sourceBox.length !== 4
        || translatedBox.length !== 4
        || !sourceBox.every(Number.isFinite)
        || !translatedBox.every(Number.isFinite)
      ) {
        return null;
      }
      return {
        itemId: `${region?.item_id || ""}`,
        source: {
          page: sourcePage,
          bbox: sourceBox,
          text: `${region?.source?.text || region?.source_text || ""}`,
        },
        translated: {
          page: translatedPage,
          bbox: translatedBox,
          text: `${region?.translated?.text || region?.translated_text || ""}`,
        },
        markdown: `${region?.markdown || region?.markdown_text || ""}`,
        regionType: `${region?.region_type || ""}`,
        status: `${region?.status || ""}`,
      };
    })
    .filter(Boolean);
}

function placeRegionBox(element, bbox, canvasBox) {
  if (!element || !canvasBox) {
    return false;
  }
  const [x0, y0, x1, y1] = bbox;
  const pageWidth = Number(canvasBox.pdfWidth || 0);
  const pageHeight = Number(canvasBox.pdfHeight || 0);
  if (!pageWidth || !pageHeight) {
    return false;
  }
  const widthScale = canvasBox.width / pageWidth;
  const heightScale = canvasBox.height / pageHeight;
  const left = x0 * widthScale;
  const top = y0 * heightScale;
  const width = (x1 - x0) * widthScale;
  const height = (y1 - y0) * heightScale;
  if (![left, top, width, height].every(Number.isFinite) || width <= 0 || height <= 0) {
    return false;
  }
  element.style.left = `${canvasBox.left + left}px`;
  element.style.top = `${canvasBox.top + top}px`;
  element.style.width = `${Math.max(1, width)}px`;
  element.style.height = `${Math.max(1, height)}px`;
  return true;
}

function regionRectFromBox(bbox, canvasBox) {
  if (!canvasBox) {
    return null;
  }
  const [x0, y0, x1, y1] = bbox;
  const pageWidth = Number(canvasBox.pdfWidth || 0);
  const pageHeight = Number(canvasBox.pdfHeight || 0);
  if (!pageWidth || !pageHeight) {
    return null;
  }
  const widthScale = canvasBox.width / pageWidth;
  const heightScale = canvasBox.height / pageHeight;
  const left = canvasBox.left + x0 * widthScale;
  const top = canvasBox.top + y0 * heightScale;
  const width = (x1 - x0) * widthScale;
  const height = (y1 - y0) * heightScale;
  if (![left, top, width, height].every(Number.isFinite) || width <= 0 || height <= 0) {
    return null;
  }
  return { left, top, right: left + width, bottom: top + height };
}

function findTranslatedRegionAtPoint(event) {
  const binding = readerRegionBinding;
  if (!binding?.translatedController || !binding.regions.length) {
    return null;
  }
  const pageElement = event.target?.closest?.(".page[data-page-number]");
  if (!pageElement || !binding.translatedController.viewerElement.contains(pageElement)) {
    return null;
  }
  const pageNumber = pageNumberOfElement(pageElement);
  if (!pageNumber) {
    return null;
  }
  const pageRect = pageElement.getBoundingClientRect();
  const x = event.clientX - pageRect.left;
  const y = event.clientY - pageRect.top;
  const canvasBox = getPageCanvasBoxWithPdfSize(binding.translatedController, pageElement, pageNumber);
  if (!canvasBox) {
    return null;
  }
  for (let index = binding.regions.length - 1; index >= 0; index -= 1) {
    const region = binding.regions[index];
    if (region.translated.page !== pageNumber) {
      continue;
    }
    const rect = regionRectFromBox(region.translated.bbox, canvasBox);
    if (rect && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
      return region;
    }
  }
  return null;
}

function drawRegionBox(controller, regionPart, layerClassName, boxClassName) {
  if (!controller || !regionPart) {
    return;
  }
  const pageElement = controller.viewerElement.querySelector(`.page[data-page-number="${regionPart.page}"]`);
  const canvasBox = getPageCanvasBoxWithPdfSize(controller, pageElement, regionPart.page);
  if (!pageElement || !canvasBox) {
    return;
  }
  const layer = ensureRegionLayer(pageElement, layerClassName);
  const box = document.createElement("div");
  box.className = boxClassName;
  if (placeRegionBox(box, regionPart.bbox, canvasBox)) {
    layer.appendChild(box);
  }
}

function showReaderRegionToast(controller, regionPart, message) {
  if (!controller || !regionPart || !message) {
    return;
  }
  const pageElement = controller.viewerElement.querySelector(`.page[data-page-number="${regionPart.page}"]`);
  const canvasBox = getPageCanvasBoxWithPdfSize(controller, pageElement, regionPart.page);
  if (!pageElement || !canvasBox) {
    return;
  }
  const rect = regionRectFromBox(regionPart.bbox, canvasBox);
  if (!rect) {
    return;
  }
  const layer = ensureRegionLayer(pageElement, "reader-translated-highlight-layer");
  layer.querySelectorAll(".reader-region-copy-toast").forEach((element) => element.remove());
  const toast = document.createElement("div");
  toast.className = "reader-region-copy-toast";
  toast.textContent = message;
  toast.style.left = `${Math.max(canvasBox.left + 8, rect.left + (rect.right - rect.left) / 2)}px`;
  toast.style.top = `${Math.max(canvasBox.top + 8, rect.top + 6)}px`;
  layer.appendChild(toast);
  window.setTimeout(() => {
    toast.classList.add("is-leaving");
  }, 760);
  window.setTimeout(() => {
    toast.remove();
  }, 1100);
}

function clearActiveRegionHighlights() {
  const binding = readerRegionBinding;
  clearRegionLayers(binding?.sourceController, "reader-source-highlight-layer");
  clearRegionLayers(binding?.translatedController, "reader-translated-highlight-layer");
}

function showReaderRegionPair(region) {
  const binding = readerRegionBinding;
  if (!binding || !region) {
    return;
  }
  clearActiveRegionHighlights();
  drawRegionBox(
    binding.sourceController,
    region.source,
    "reader-source-highlight-layer",
    "reader-region-highlight-box",
  );
  drawRegionBox(
    binding.translatedController,
    region.translated,
    "reader-translated-highlight-layer",
    "reader-region-highlight-box",
  );
}

function hideReaderRegionPair() {
  if (selectedReaderRegion) {
    showReaderRegionPair(selectedReaderRegion);
    return;
  }
  clearActiveRegionHighlights();
}

function handleTranslatedRegionMouseMove(event) {
  const region = findTranslatedRegionAtPoint(event);
  if (region?.itemId === hoveredReaderRegion?.itemId) {
    return;
  }
  hoveredReaderRegion = region;
  if (region) {
    showReaderRegionPair(region);
  } else {
    hideReaderRegionPair();
  }
}

function handleTranslatedRegionMouseLeave() {
  hoveredReaderRegion = null;
  hideReaderRegionPair();
}

function handleTranslatedRegionClick(event) {
  const region = findTranslatedRegionAtPoint(event);
  if (!region) {
    return;
  }
  selectReaderRegion(region);
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) {
    throw new Error("copy command failed");
  }
}

function selectReaderRegion(region) {
  selectedReaderRegion = selectedReaderRegion?.itemId === region?.itemId ? null : region;
  if (selectedReaderRegion) {
    showReaderRegionPair(selectedReaderRegion);
  } else {
    clearActiveRegionHighlights();
  }
}

function escapeHtml(value) {
  return `${value ?? ""}`
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function firstText(...values) {
  for (const value of values) {
    const text = `${value ?? ""}`.trim();
    if (text) {
      return text;
    }
  }
  return "";
}

function removeReaderMarkdownPopover() {
  document.querySelector("#reader-region-markdown-popover")?.remove();
}

function formatReaderRegionMarkdownPayload(payload) {
  const item = payload?.item || payload || {};
  const markdown = firstText(
    payload?.markdown,
    item.markdown,
    item.markdown_text,
    item.markdown_source,
    item.protected_markdown,
    item.render_markdown,
    item.typst_markdown,
  );
  const translated = firstText(
    payload?.translated?.text,
    payload?.translated_text,
    item.translated_text,
    item.translation_unit_translated_text,
    item.group_translated_text,
    item.protected_translated_text,
    item.translation_unit_protected_translated_text,
    item.group_protected_translated_text,
  );
  const source = firstText(payload?.source?.text, payload?.source_text, item.source_text, item.text, item.raw_text);
  return {
    title: firstText(payload?.item_id, item.item_id, "translation item"),
    primaryLabel: markdown ? "Markdown" : (translated ? "译文" : "原文"),
    primaryText: markdown || translated || source || "该区域暂无可显示文本",
    source,
    translated,
  };
}

function renderReaderTextBlock(label, text) {
  const normalized = `${text || ""}`;
  if (!normalized.trim()) {
    return "";
  }
  return `
    <section class="reader-region-markdown-section">
      <div class="reader-region-markdown-label-row">
        <span class="reader-region-markdown-label">${escapeHtml(label)}</span>
        <button type="button" class="reader-region-copy-btn" data-copy-text="${escapeHtml(normalized)}">复制</button>
      </div>
      <pre>${escapeHtml(normalized)}</pre>
    </section>
  `;
}

async function copyReaderRegionText(button) {
  const text = button?.dataset?.copyText || "";
  if (!text) {
    return;
  }
  try {
    await copyTextToClipboard(text);
    const previous = button.textContent;
    button.textContent = "已复制";
    window.setTimeout(() => {
      button.textContent = previous || "复制";
    }, 900);
  } catch {
    button.textContent = "复制失败";
    window.setTimeout(() => {
      button.textContent = "复制";
    }, 900);
  }
}

async function fetchReaderRegionPayload(region) {
  if (region?.markdown || region?.source?.text || region?.translated?.text) {
    return region;
  }
  const binding = readerRegionBinding;
  if (!binding?.jobId || !binding?.fetchTranslationItem || !region?.itemId) {
    return null;
  }
  const cacheKey = `${binding.jobId}:${region.itemId}`;
  if (readerRegionItemCache.has(cacheKey)) {
    return readerRegionItemCache.get(cacheKey);
  }
  const request = binding.fetchTranslationItem(binding.jobId, region.itemId, binding.apiPrefix);
  readerRegionItemCache.set(cacheKey, request);
  return request;
}

async function handleTranslatedRegionDoubleClick(event) {
  const region = findTranslatedRegionAtPoint(event);
  if (!region) {
    return;
  }
  event.preventDefault();
  showReaderRegionPair(region);
  try {
    const payload = await fetchReaderRegionPayload(region);
    const formatted = formatReaderRegionMarkdownPayload(payload);
    await copyTextToClipboard(formatted.translated || formatted.primaryText);
    showReaderRegionToast(readerRegionBinding?.translatedController, region.translated, "已复制");
  } catch {
    showReaderRegionToast(readerRegionBinding?.translatedController, region.translated, "复制失败");
    // Keep text selection behavior unaffected if copy is unavailable.
  }
}

function positionReaderMarkdownPopover(popover, event) {
  const margin = 12;
  const width = Math.min(360, window.innerWidth - margin * 2);
  popover.style.width = `${Math.max(220, width)}px`;
  popover.style.left = `${Math.min(event.clientX + 10, window.innerWidth - width - margin)}px`;
  popover.style.top = `${Math.min(event.clientY + 10, window.innerHeight - 180)}px`;
}

function renderReaderMarkdownPopover(event, region, state) {
  removeReaderMarkdownPopover();
  const popover = document.createElement("div");
  popover.id = "reader-region-markdown-popover";
  popover.className = "reader-region-markdown-popover";
  popover.innerHTML = `
    <div class="reader-region-markdown-head">
      <span>${escapeHtml(region?.itemId || "区域文本")}</span>
      <button type="button" class="reader-region-markdown-close" aria-label="关闭">×</button>
    </div>
    <div class="reader-region-markdown-body">${escapeHtml(state?.message || "正在读取...")}</div>
  `;
  document.body.appendChild(popover);
  positionReaderMarkdownPopover(popover, event);
  for (const eventName of ["mousedown", "mouseup", "click", "dblclick", "contextmenu"]) {
    popover.addEventListener(eventName, (popoverEvent) => {
      popoverEvent.stopPropagation();
    });
  }
  popover.querySelector(".reader-region-markdown-close")?.addEventListener("click", removeReaderMarkdownPopover);
  popover.addEventListener("click", (clickEvent) => {
    const copyButton = clickEvent.target?.closest?.(".reader-region-copy-btn");
    if (!copyButton || !popover.contains(copyButton)) {
      return;
    }
    clickEvent.preventDefault();
    copyReaderRegionText(copyButton);
  });
  return popover;
}

async function showReaderRegionMarkdown(event, region) {
  event.preventDefault();
  event.stopPropagation();
  showReaderRegionPair(region);
  const binding = readerRegionBinding;
  if (!binding?.jobId || !binding?.fetchTranslationItem || !region?.itemId) {
    renderReaderMarkdownPopover(event, region, { message: "缺少 item_id，无法读取文本" });
    return;
  }
  const popover = renderReaderMarkdownPopover(event, region, { message: "正在读取..." });
  try {
    const payload = await fetchReaderRegionPayload(region);
    const formatted = formatReaderRegionMarkdownPayload(payload);
    popover.querySelector(".reader-region-markdown-body").innerHTML = `
      ${renderReaderTextBlock(formatted.primaryLabel, formatted.primaryText)}
      ${formatted.source && formatted.primaryText !== formatted.source ? renderReaderTextBlock("原文", formatted.source) : ""}
    `;
  } catch (error) {
    popover.querySelector(".reader-region-markdown-body").textContent = error?.message || "读取失败";
  }
}

function scheduleRegionOverlayRender() {
  if (!readerRegionBinding || regionOverlayTicking) {
    return;
  }
  regionOverlayTicking = true;
  window.requestAnimationFrame(() => {
    regionOverlayTicking = false;
    if (hoveredReaderRegion) {
      showReaderRegionPair(hoveredReaderRegion);
    } else if (selectedReaderRegion) {
      showReaderRegionPair(selectedReaderRegion);
    }
  });
}

export function scheduleScaleRefresh() {
  if (resizeTicking) {
    return;
  }
  resizeTicking = true;
  window.requestAnimationFrame(() => {
    resizeTicking = false;
    viewerControllers.forEach((controller) => {
      applyViewerScale(controller);
    });
    schedulePageRowSync();
  });
}

export function bindPrimaryViewer(controller, onPageChange) {
  if (!controller) {
    return;
  }
  if (controller.primaryScrollHandler) {
    controller.scrollShell.removeEventListener("scroll", controller.primaryScrollHandler);
  }
  let ticking = false;
  controller.primaryScrollHandler = () => {
    if (ticking) {
      return;
    }
    ticking = true;
    window.requestAnimationFrame(() => {
      ticking = false;
      const containerRect = controller.scrollShell.getBoundingClientRect();
      const focusY = containerRect.top + Math.min(containerRect.height * 0.35, 320);
      let bestPage = 1;
      let bestDistance = Number.POSITIVE_INFINITY;
      controller.viewerElement.querySelectorAll(".page[data-page-number]").forEach((pageElement) => {
        const rect = pageElement.getBoundingClientRect();
        const pageFocus = rect.top + Math.min(rect.height * 0.35, 320);
        const distance = Math.abs(pageFocus - focusY);
        if (distance < bestDistance) {
          bestDistance = distance;
          bestPage = pageNumberOfElement(pageElement) || bestPage;
        }
      });
      onPageChange?.(bestPage);
    });
  };
  controller.scrollShell.addEventListener("scroll", controller.primaryScrollHandler, { passive: true });
  controller.primaryScrollHandler();
}

function createViewerController(key) {
  const scrollShell = $("reader-scroll-shell");
  const viewerHost = $(`${key}-viewer-host`);
  const viewerElement = $(`${key}-viewer`);
  if (!scrollShell || !viewerHost || !viewerElement) {
    return null;
  }

  const controller = {
    key,
    scrollShell,
    viewerHost,
    viewerElement,
    basePageWidth: 0,
    currentScale: 0,
    pdfDocument: null,
    pageViewports: new Map(),
    renderedPages: new Set(),
    renderTasks: new Map(),
    visiblePages: new Set(),
    pageObserver: null,
    primaryScrollHandler: null,
  };
  viewerControllers.set(key, controller);
  return controller;
}

function outputScaleForPage(width, height) {
  const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, MAX_READER_OUTPUT_SCALE));
  const pixels = width * height * dpr * dpr;
  if (pixels <= MAX_READER_CANVAS_PIXELS) {
    return dpr;
  }
  return Math.max(1, Math.sqrt(MAX_READER_CANVAS_PIXELS / Math.max(1, width * height)));
}

function pageElementFor(controller, pageNumber) {
  return controller?.viewerElement.querySelector(`.page[data-page-number="${pageNumber}"]`) || null;
}

function setManualPageSize(controller, pageElement, pageNumber) {
  const viewport = controller.pageViewports.get(Number(pageNumber));
  if (!viewport || !pageElement) {
    return;
  }
  const width = Math.floor(viewport.width * controller.currentScale);
  const height = Math.floor(viewport.height * controller.currentScale);
  pageElement.style.width = `${width}px`;
  pageElement.style.height = `${height}px`;
  const canvasWrapper = pageElement.querySelector(".canvasWrapper");
  if (canvasWrapper) {
    canvasWrapper.style.width = `${width}px`;
    canvasWrapper.style.height = `${height}px`;
  }
}

function updateManualPageSizes(controller) {
  controller?.viewerElement.querySelectorAll(".page[data-page-number]").forEach((pageElement) => {
    setManualPageSize(controller, pageElement, pageNumberOfElement(pageElement));
  });
}

async function renderManualPage(controller, pageNumber) {
  if (
    !controller?.pdfDocument
    || controller.renderedPages.has(pageNumber)
    || controller.renderTasks.has(pageNumber)
  ) {
    return;
  }
  const pageElement = pageElementFor(controller, pageNumber);
  const canvas = pageElement?.querySelector("canvas");
  if (!pageElement || !canvas) {
    return;
  }
  try {
    const pdfPage = await controller.pdfDocument.getPage(pageNumber);
    const baseViewport = pdfPage.getViewport({ scale: 1 });
    controller.pageViewports.set(pageNumber, {
      width: baseViewport.width,
      height: baseViewport.height,
    });
    setManualPageSize(controller, pageElement, pageNumber);
    const viewport = pdfPage.getViewport({ scale: controller.currentScale });
    const outputScale = outputScaleForPage(viewport.width, viewport.height);
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) {
      return;
    }
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;
    context.setTransform(outputScale, 0, 0, outputScale, 0, 0);
    const renderTask = pdfPage.render({ canvas, canvasContext: context, viewport });
    controller.renderTasks.set(pageNumber, renderTask);
    await renderTask.promise;
    controller.renderedPages.add(pageNumber);
  } catch (error) {
    if (error?.name !== "RenderingCancelledException") {
      pageElement.dataset.renderError = "1";
    }
  } finally {
    controller.renderTasks.delete(pageNumber);
    schedulePageRowSync();
    scheduleRegionOverlayRender();
  }
}

function scheduleVisibleManualPages(controller) {
  const visiblePages = [...(controller?.visiblePages || [])].sort((a, b) => a - b);
  visiblePages.slice(0, 8).forEach((pageNumber) => {
    void renderManualPage(controller, pageNumber);
  });
}

function createManualPageElement(controller, pageNumber, fallbackViewport) {
  const pageElement = document.createElement("div");
  pageElement.className = "page";
  pageElement.dataset.pageNumber = `${pageNumber}`;
  pageElement.setAttribute("role", "region");
  const canvasWrapper = document.createElement("div");
  canvasWrapper.className = "canvasWrapper";
  const canvas = document.createElement("canvas");
  canvasWrapper.appendChild(canvas);
  pageElement.appendChild(canvasWrapper);
  controller.viewerElement.appendChild(pageElement);
  controller.pageViewports.set(pageNumber, {
    width: fallbackViewport.width,
    height: fallbackViewport.height,
  });
  setManualPageSize(controller, pageElement, pageNumber);
  controller.pageObserver.observe(pageElement);
}

function mountManualPages(controller, pdfDocument, firstViewport) {
  controller.pageObserver?.disconnect?.();
  controller.renderTasks.forEach((task) => task?.cancel?.());
  controller.viewerElement.innerHTML = "";
  controller.pdfDocument = pdfDocument;
  controller.pageViewports.clear();
  controller.renderedPages.clear();
  controller.renderTasks.clear();
  controller.visiblePages.clear();
  controller.pageObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      const pageNumber = pageNumberOfElement(entry.target);
      if (!pageNumber) {
        return;
      }
      if (entry.isIntersecting) {
        controller.visiblePages.add(pageNumber);
      } else {
        controller.visiblePages.delete(pageNumber);
      }
    });
    scheduleVisibleManualPages(controller);
  }, {
    root: controller.scrollShell,
    rootMargin: "900px 0px",
    threshold: 0.01,
  });
  for (let pageNumber = 1; pageNumber <= pdfDocument.numPages; pageNumber += 1) {
    createManualPageElement(controller, pageNumber, firstViewport);
  }
}

async function loadPdfDocument({ itemOrUrl }) {
  const url = typeof itemOrUrl === "string" ? itemOrUrl : resolveReaderArtifactUrl(itemOrUrl);
  if (!url) {
    return null;
  }
  return pdfjsLib.getDocument({
    url,
    httpHeaders: buildApiHeaders(),
    withCredentials: false,
    disableRange: false,
    disableStream: false,
    rangeChunkSize: READER_RANGE_CHUNK_SIZE,
    cMapUrl: PDFJS_CMAP_URL,
    cMapPacked: true,
    standardFontDataUrl: PDFJS_STANDARD_FONT_DATA_URL,
  }).promise;
}

export async function mountPdfViewer({
  key,
  itemOrUrl,
  label,
  emptyId,
}) {
  const viewerWrap = $(`${key}-wrap`);
  const empty = $(emptyId);
  const controller = getViewerController(key) || createViewerController(key);
  if (!viewerWrap || !empty || !controller) {
    return null;
  }

  void label;
  const pdfDocument = await loadPdfDocument({ itemOrUrl });
  if (!pdfDocument) {
    showReaderPaneEmpty(key, emptyId);
    return null;
  }

  const firstPage = await pdfDocument.getPage(1);
  const firstViewport = firstPage.getViewport({ scale: 1 });
  controller.basePageWidth = firstViewport.width;
  mountManualPages(controller, pdfDocument, firstViewport);
  applyViewerScale(controller);
  controller.visiblePages.add(1);
  if (pdfDocument.numPages > 1) {
    controller.visiblePages.add(2);
  }
  scheduleVisibleManualPages(controller);

  showReaderPaneReady(key, emptyId);

  return {
    key,
    pagesCount: pdfDocument.numPages,
    controller,
  };
}

export function bindResizeRefresh() {
  window.addEventListener("resize", scheduleScaleRefresh);
}

export function bindReaderRegionHover({
  regions,
  sourceController,
  translatedController,
  jobId = "",
  apiPrefix = "",
  fetchTranslationItem = null,
} = {}) {
  const normalizedRegions = normalizeReaderRegions(regions);
  if (!normalizedRegions.length || !sourceController || !translatedController) {
    return;
  }
  readerRegionBinding = {
    regions: normalizedRegions,
    sourceController,
    translatedController,
    jobId,
    apiPrefix,
    fetchTranslationItem,
  };
  selectedReaderRegion = null;
  hoveredReaderRegion = null;
  if (translatedController.viewerElement.dataset.readerRegionHitTestBound !== "1") {
    translatedController.viewerElement.dataset.readerRegionHitTestBound = "1";
    translatedController.viewerElement.addEventListener("mousemove", handleTranslatedRegionMouseMove);
    translatedController.viewerElement.addEventListener("mouseleave", handleTranslatedRegionMouseLeave);
    translatedController.viewerElement.addEventListener("click", handleTranslatedRegionClick);
    translatedController.viewerElement.addEventListener("dblclick", handleTranslatedRegionDoubleClick);
    translatedController.viewerElement.addEventListener("contextmenu", (event) => {
      const region = findTranslatedRegionAtPoint(event);
      if (region) {
        showReaderRegionMarkdown(event, region);
      }
    });
  }
  scheduleRegionOverlayRender();
}
