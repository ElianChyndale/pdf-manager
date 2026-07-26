export const RULE_PROFILE_GENERAL_SCI = "general_sci";
export const RULE_PROFILE_ENGINEERING_DRAWING = "engineering_drawing";

const RULE_PROFILES = new Set([
  RULE_PROFILE_GENERAL_SCI,
  RULE_PROFILE_ENGINEERING_DRAWING,
]);
const OUTPUT_MODES = new Set(["bilingual_overlay", "dual"]);

export function normalizeRuleProfile(value, fallback = RULE_PROFILE_GENERAL_SCI) {
  const candidate = `${value || ""}`.trim();
  return RULE_PROFILES.has(candidate) ? candidate : fallback;
}

export function normalizeOutputModes(values) {
  const source = Array.isArray(values)
    ? values
    : `${values || ""}`.split(",");
  return [...new Set(
    source
      .map((value) => `${value || ""}`.trim())
      .filter((value) => OUTPUT_MODES.has(value)),
  )];
}

export function optionalLegacyTranslationSource(legacyTranslationUploadId) {
  const uploadId = `${legacyTranslationUploadId || ""}`.trim();
  return uploadId ? { legacy_translation_upload_id: uploadId } : {};
}

export function optionalRenderOutputModes(outputModes) {
  const normalized = normalizeOutputModes(outputModes);
  return normalized.length > 0 ? { output_modes: normalized } : {};
}
