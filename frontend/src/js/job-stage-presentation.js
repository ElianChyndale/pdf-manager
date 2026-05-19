import {
  summarizeStageDetail,
  summarizeStageKey,
  summarizeStageLabel,
  summarizeStageProgressText,
  progressFromText,
  stageSubtypeOf,
} from "./job-status-summary.js";
import {
  ocrProgressFallbackForRawStage,
  rawStageOfPayload,
  visualStageKeyForRawStage,
} from "./job-stage-contract.js";

function stageRank(stageKey) {
  return {
    queued: 0,
    ocr: 1,
    translate: 2,
    render: 3,
    done: 4,
  }[stageKey] ?? 0;
}

function numberOrNull(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function firstNumber(...values) {
  for (const value of values) {
    const num = numberOrNull(value);
    if (num !== null) {
      return num;
    }
  }
  return null;
}

function strongestStageKey(...payloads) {
  return payloads
    .map((payload) => summarizeStageKey(payload || {}))
    .filter(Boolean)
    .reduce((best, key) => stageRank(key) > stageRank(best) ? key : best, "");
}

function keepForwardStageKey(job, eventPayload, eventsPayload) {
  const jobStageKey = strongestStageKey(job, eventsPayload?.live_stage);
  const eventStageKey = summarizeStageKey(eventPayload);
  return stageRank(eventStageKey) >= stageRank(jobStageKey) ? eventStageKey : jobStageKey;
}

function latestStageEvent(job, eventsPayload) {
  const items = Array.isArray(eventsPayload?.items) ? eventsPayload.items : [];
  const currentStage = `${job?.current_stage || job?.stage || ""}`.trim();
  const currentStageKey = summarizeStageKey(job);
  const findMatchingEvent = (allowBroadStage, requireProgress = false) => {
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index] || {};
      const itemStage = `${item.stage || ""}`.trim();
      const providerStage = `${item.provider_stage || ""}`.trim();
      const userStage = `${item.user_stage || item.payload?.user_stage || ""}`.trim();
      const itemStageForMatch = itemStage || providerStage || userStage;
      if (!itemStageForMatch) {
        continue;
      }
      const progress = progressFromEvent(item);
      if (requireProgress && (progress.current === null || progress.total === null)) {
        continue;
      }
      const itemPayload = {
        ...job,
        current_stage: itemStageForMatch,
        stage_detail: item.stage_detail || item.message || "",
        user_stage: userStage,
        substage: item.substage || item.payload?.substage || "",
        progress_current: progress.current,
        progress_total: progress.total,
      };
      const itemStageKey = summarizeStageKey(itemPayload);
      if (currentStage) {
        const exactMatch = itemStageForMatch === currentStage;
        if (!exactMatch && (!allowBroadStage || itemStageKey !== currentStageKey)) {
          continue;
        }
      } else if (currentStageKey && itemStageKey !== currentStageKey) {
        continue;
      }
      if (!item.stage_detail && !item.message && progress.current === null) {
        continue;
      }
      return item;
    }
    return null;
  };
  const exactEvent = findMatchingEvent(false);
  if (currentStageKey === "ocr" || currentStageKey === "translate" || currentStageKey === "render") {
    const desiredSubstageKey = currentStageKey === "translate"
      ? stageSubtypeOf(eventsPayload?.live_stage || job)
      : "";
    if (desiredSubstageKey) {
      for (let index = items.length - 1; index >= 0; index -= 1) {
        const item = items[index] || {};
        const itemStage = `${item.stage || ""}`.trim();
        const providerStage = `${item.provider_stage || ""}`.trim();
        const userStage = `${item.user_stage || item.payload?.user_stage || ""}`.trim();
        const itemStageForMatch = itemStage || providerStage || userStage;
        if (!itemStageForMatch) {
          continue;
        }
        const progress = progressFromEvent(item);
        const itemPayload = {
          ...job,
          current_stage: itemStageForMatch,
          stage_detail: item.stage_detail || item.message || "",
          user_stage: userStage,
          substage: item.substage || item.payload?.substage || "",
          progress_current: progress.current,
          progress_total: progress.total,
        };
        if (summarizeStageKey(itemPayload) === currentStageKey && stageSubtypeOf(itemPayload) === desiredSubstageKey) {
          return item;
        }
      }
    }
    const broadEvent = findMatchingEvent(true, true) || findMatchingEvent(true);
    if (broadEvent) {
      return broadEvent;
    }
  }
  if (exactEvent) {
    return exactEvent;
  }
  return findMatchingEvent(true);
}

function progressFromEvent(event) {
  const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
  const current = firstNumber(
    event?.progress_current,
    payload.progress_current,
    payload.progress?.current,
    payload.current,
    payload.current_page,
    payload.extracted_pages,
    payload.extractedPages,
    payload.page_number,
    payload.page,
  );
  const total = firstNumber(
    event?.progress_total,
    payload.progress_total,
    payload.progress?.total,
    payload.total,
    payload.total_pages,
    payload.totalPages,
    payload.page_count,
    payload.pages,
  );
  return { current, total };
}

function stagePayloadFromEvent(job, item, progress) {
  const userStage = item?.user_stage || item?.payload?.user_stage || "";
  const rawStage = item?.stage || item?.provider_stage || userStage;
  return {
    ...job,
    status: item?.status || "running",
    user_stage: userStage,
    current_stage: rawStage,
    stage: item?.stage || "",
    substage: item?.substage || item?.payload?.substage || "",
    stage_detail: item?.stage_detail || item?.message || item?.payload?.stage_detail || "",
    progress_unit: item?.progress_unit || item?.payload?.progress_unit || "",
    progress_current: progress.current,
    progress_total: progress.total,
  };
}

function progressPercentFromEvent(event) {
  const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
  return firstNumber(
    event?.progress_percent,
    payload.progress_percent,
    payload.progress?.percent,
    event?.percent,
    payload.percent,
  );
}

function progressUnitPriority(unit = "") {
  switch (`${unit || ""}`.trim()) {
    case "page":
    case "batch":
      return 3;
    case "percent":
      return 2;
    case "step":
      return 1;
    default:
      return 0;
  }
}

function visualStageKeyForEventPayload(payload = {}, stageKey = "") {
  const substage = `${payload?.substage || payload?.payload?.substage || ""}`.trim().toLowerCase();
  if (stageKey === "ocr" && substage) {
    if (substage.includes("upload") || substage.includes("submitting") || substage.includes("submit")) {
      return "ocr_upload";
    }
    if (substage.includes("processing") || substage.includes("recogn") || substage.includes("running")) {
      return "ocr_processing";
    }
    if (substage.includes("result")) {
      return "ocr_result_ready";
    }
    if (substage.includes("normaliz") || substage.includes("standard")) {
      return "ocr_normalizing";
    }
  }
  return visualStageKeyForRawStage(rawStageOfPayload(payload), stageKey);
}

function shouldReplaceStageProgress(previous, next) {
  if (!previous) {
    return true;
  }
  if (
    next.current > 0
    && next.total > 0
    && next.current >= next.total
    && (next.progressUnit === "page" || next.progressUnit === "none" || next.visualStageKey === "ocr_result_ready")
  ) {
    return true;
  }
  const previousPriority = progressUnitPriority(previous.progressUnit);
  const nextPriority = progressUnitPriority(next.progressUnit);
  if (nextPriority !== previousPriority) {
    return nextPriority > previousPriority;
  }
  return true;
}

function shouldReplaceCurrentStageProgress(previous, next) {
  if (!previous) {
    return true;
  }
  const previousSeq = Number(previous.seq);
  const nextSeq = Number(next.seq);
  if (Number.isFinite(previousSeq) && Number.isFinite(nextSeq) && nextSeq !== previousSeq) {
    return nextSeq > previousSeq;
  }
  const previousTs = Date.parse(previous.ts || "");
  const nextTs = Date.parse(next.ts || "");
  if (Number.isFinite(previousTs) && Number.isFinite(nextTs) && nextTs !== previousTs) {
    return nextTs > previousTs;
  }
  return true;
}

function eventIdentity(item = {}) {
  const seq = Number(item.seq);
  const ts = Date.parse(item.ts || item.created_at || "");
  return {
    seq: Number.isFinite(seq) ? seq : null,
    ts: Number.isFinite(ts) ? ts : null,
  };
}

function compareProgressEventOrder(previous, next) {
  if (!previous) {
    return 1;
  }
  const previousSeq = Number(previous.seq);
  const nextSeq = Number(next.seq);
  if (Number.isFinite(previousSeq) && Number.isFinite(nextSeq) && nextSeq !== previousSeq) {
    return nextSeq > previousSeq ? 1 : -1;
  }
  const previousTs = Date.parse(previous.ts || "");
  const nextTs = Date.parse(next.ts || "");
  if (Number.isFinite(previousTs) && Number.isFinite(nextTs) && nextTs !== previousTs) {
    return nextTs > previousTs ? 1 : -1;
  }
  return 1;
}

function normalizeProgressRecord(job, item, itemStage) {
  const progress = progressFromEvent(item);
  const progressPercent = progressPercentFromEvent(item);
  if (
    (progress.current === null || progress.total === null || progress.total <= 0)
    && progressPercent === null
  ) {
    return null;
  }
  const payload = stagePayloadFromEvent(job, { ...item, stage: itemStage }, progress);
  const stageKey = summarizeStageKey(payload);
  if (!["ocr", "translate", "render"].includes(stageKey)) {
    return null;
  }
  const displayPayload = { ...payload };
  const visualStageKey = visualStageKeyForEventPayload(displayPayload, stageKey);
  const substageKey = stageSubtypeOf(displayPayload);
  const identity = eventIdentity(item);
  return {
    item,
    payload: displayPayload,
    stageKey,
    current: progress.current,
    total: progress.total,
    progressPercent,
    progressUnit: displayPayload.progress_unit,
    progressText: summarizeStageProgressText(displayPayload),
    visualStageKey,
    substageKey,
    indeterminate: stageKey === "ocr" && progress.current <= 0 && progress.total > 0,
    seq: identity.seq,
    ts: item?.ts || item?.created_at,
  };
}

function collectLatestCurrentStageProgress(job, eventsPayload, stageKey = "", substageKey = "") {
  const items = Array.isArray(eventsPayload?.items) ? eventsPayload.items : [];
  let latest = null;
  let latestSameSubstage = null;
  for (const item of items) {
    const itemStage = `${item?.stage || item?.provider_stage || item?.user_stage || item?.payload?.user_stage || ""}`.trim();
    if (!itemStage) {
      continue;
    }
    const next = normalizeProgressRecord(job, item, itemStage);
    if (!next || next.stageKey !== stageKey) {
      continue;
    }
    if (shouldReplaceCurrentStageProgress(latest, next)) {
      latest = next;
    }
    if (substageKey && next.substageKey === substageKey && shouldReplaceCurrentStageProgress(latestSameSubstage, next)) {
      latestSameSubstage = next;
    }
  }
  return latestSameSubstage || latest;
}

function translationSubstageKeyFromTextPayload(payload = {}) {
  if (stageKeyOfPayload(payload) !== "translate") {
    return "";
  }
  return stageSubtypeOf(payload);
}

function stageKeyOfPayload(payload = {}) {
  return summarizeStageKey(payload);
}

export function collectStageProgressByKey(job, eventsPayload) {
  const items = Array.isArray(eventsPayload?.items) ? eventsPayload.items : [];
  const progressByKey = {};
  const progressBySubstage = {};
  for (const item of items) {
    const itemStage = `${item?.stage || item?.provider_stage || item?.user_stage || item?.payload?.user_stage || ""}`.trim();
    if (!itemStage) {
      continue;
    }
    const nextProgress = normalizeProgressRecord(job, item, itemStage);
    if (!nextProgress) {
      continue;
    }
    const { stageKey, substageKey } = nextProgress;
    if (shouldReplaceStageProgress(progressByKey[stageKey], nextProgress)) {
      progressByKey[stageKey] = nextProgress;
    }
    if (stageKey === "translate" && substageKey) {
      const bySubstage = progressBySubstage[stageKey] || {};
      if (compareProgressEventOrder(bySubstage[substageKey], nextProgress) >= 0) {
        bySubstage[substageKey] = nextProgress;
      }
      progressBySubstage[stageKey] = bySubstage;
    }
  }
  Object.entries(progressBySubstage).forEach(([stageKey, bySubstage]) => {
    progressByKey[stageKey] = {
      ...progressByKey[stageKey],
      bySubstage,
    };
  });
  return progressByKey;
}

function jobProgress(job = {}) {
  const textProgress = progressFromText(job);
  const current = firstNumber(job?.progress_current, job?.progress?.current);
  const total = firstNumber(job?.progress_total, job?.progress?.total);
  return {
    current: current ?? textProgress.current,
    total: total ?? textProgress.total,
  };
}

function stageProgressMatches(stageKey, eventPayload) {
  return Boolean(stageKey) && summarizeStageKey(eventPayload) === stageKey;
}

function stageFallbackProgress(stageKey, job = {}) {
  return stageKey === "ocr" ? ocrProgressFallbackForRawStage(rawStageOfPayload(job)) : null;
}

function visualStageKeyFor(job = {}, stageKey = "") {
  const substage = `${job?.substage || job?.payload?.substage || ""}`.trim().toLowerCase();
  if (stageKey === "ocr" && substage) {
    return visualStageKeyForEventPayload(job, stageKey);
  }
  return visualStageKeyForRawStage(rawStageOfPayload(job), stageKey);
}

export function resolveDisplayedStagePresentation(job, eventsPayload) {
  const fallbackProgress = jobProgress(job);
  const fallbackStageKey = summarizeStageKey(job);
  const stageFallback = stageFallbackProgress(fallbackStageKey, job);
  const fallback = {
    stageKey: fallbackStageKey,
    visualStageKey: visualStageKeyFor(job, fallbackStageKey),
    label: summarizeStageLabel(job),
    detail: summarizeStageDetail(job),
    progressText: summarizeStageProgressText(job) || stageFallback?.text || "",
    progressCurrent: fallbackProgress.current ?? stageFallback?.current ?? null,
    progressTotal: fallbackProgress.total ?? stageFallback?.total ?? null,
    substageKey: stageSubtypeOf(job),
    progressIndeterminate: fallbackProgress.current === null && fallbackProgress.total === null && Boolean(stageFallback),
  };
  const event = latestStageEvent(job, eventsPayload);
  if (!event) {
    return fallback;
  }
  const eventProgress = progressFromEvent(event);
  const rawEventPayload = {
    ...job,
    status: job.status,
    user_stage: event.user_stage || event.payload?.user_stage || "",
    current_stage: event.stage || event.provider_stage || event.user_stage || event.payload?.user_stage || job.current_stage || job.stage || "",
    substage: event.substage || event.payload?.substage || "",
    stage_detail: event.stage_detail || event.message || event.payload?.stage_detail || job.stage_detail || "",
    progress_unit: event.progress_unit || event.payload?.progress_unit || "",
    progress_current: eventProgress.current,
    progress_total: eventProgress.total,
  };
  const eventMatchesCurrentStage = stageProgressMatches(fallback.stageKey, rawEventPayload);
  const progress = {
    current: eventProgress.current ?? (eventMatchesCurrentStage ? fallbackProgress.current : null),
    total: eventProgress.total ?? (eventMatchesCurrentStage ? fallbackProgress.total : null),
  };
  const eventPayload = {
    ...rawEventPayload,
    progress_current: progress.current ?? stageFallback?.current ?? null,
    progress_total: progress.total ?? stageFallback?.total ?? null,
  };
  const eventProgressText = summarizeStageProgressText(eventPayload);
  const stageKey = keepForwardStageKey(job, eventPayload, eventsPayload);
  const eventSubstageKey = translationSubstageKeyFromTextPayload(eventPayload) || stageSubtypeOf(eventPayload);
  const latestCurrentProgress = collectLatestCurrentStageProgress(job, eventsPayload, stageKey, eventSubstageKey);
  const latestProgressPayload = latestCurrentProgress
    ? {
        ...latestCurrentProgress.payload,
        progress_current: latestCurrentProgress.current,
        progress_total: latestCurrentProgress.total,
      }
    : null;
  const currentProgressText = latestProgressPayload ? summarizeStageProgressText(latestProgressPayload) : eventProgressText;
  const currentVisualPayload = latestProgressPayload || eventPayload;
  const currentSubstagePayload = latestProgressPayload || eventPayload;
  const currentProgressIndeterminate = latestCurrentProgress
    ? latestCurrentProgress.current === null
      && latestCurrentProgress.total !== null
      && stageKey === "ocr"
    : eventProgress.current === null && eventProgress.total === null && Boolean(stageFallback);
  return {
    stageKey,
    visualStageKey: visualStageKeyFor(currentVisualPayload, stageKey),
    label: stageKey === summarizeStageKey(eventPayload) ? summarizeStageLabel(eventPayload) : summarizeStageLabel(job),
    detail: summarizeStageDetail(eventPayload),
    progressText: currentProgressText || stageFallback?.text || "",
    progressCurrent: latestCurrentProgress?.current ?? eventPayload.progress_current,
    progressTotal: latestCurrentProgress?.total ?? eventPayload.progress_total,
    progressPercent: latestCurrentProgress?.progressPercent ?? null,
    substageKey: stageSubtypeOf(currentSubstagePayload),
    progressIndeterminate: currentProgressIndeterminate,
  };
}
