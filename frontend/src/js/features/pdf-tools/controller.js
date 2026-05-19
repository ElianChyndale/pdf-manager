import { openMergePanel } from "./panel-merge.js";
import { openSplitPanel } from "./panel-split.js";
import { openCompressPanel } from "./panel-compress.js";
import { openRotatePanel } from "./panel-rotate.js";
import { openMetadataPanel } from "./panel-metadata.js";
import { openEncryptPanel } from "./panel-encrypt.js";

export function mountPdfToolsFeature() {
  const toolbox = document.getElementById("pdf-toolbox");
  if (!toolbox) return;

  const toolMap = {
    "tool-merge": () => openMergePanel(),
    "tool-split": () => openSplitPanel(),
    "tool-compress": () => openCompressPanel(),
    "tool-rotate": () => openRotatePanel(),
    "tool-metadata": () => openMetadataPanel(),
    "tool-encrypt": () => openEncryptPanel(),
  };

  toolbox.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tool]");
    if (btn) {
      const tool = btn.dataset.tool;
      const handler = toolMap[tool];
      if (handler) handler();
    }
  });
}
