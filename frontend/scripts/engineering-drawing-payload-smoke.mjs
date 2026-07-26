#!/usr/bin/env node

import {
  normalizeOutputModes,
  normalizeRuleProfile,
  optionalLegacyTranslationSource,
  optionalRenderOutputModes,
  RULE_PROFILE_ENGINEERING_DRAWING,
  RULE_PROFILE_GENERAL_SCI,
} from "../src/js/features/workflow/payload-options.js";

function assertJsonEqual(actual, expected, label) {
  const actualJson = JSON.stringify(actual);
  const expectedJson = JSON.stringify(expected);
  if (actualJson !== expectedJson) {
    throw new Error(`${label}: expected ${expectedJson}, got ${actualJson}`);
  }
}

assertJsonEqual(
  normalizeRuleProfile("engineering_drawing"),
  RULE_PROFILE_ENGINEERING_DRAWING,
  "engineering drawing profile",
);
assertJsonEqual(
  normalizeRuleProfile("unknown"),
  RULE_PROFILE_GENERAL_SCI,
  "unknown profile preserves safe default",
);
assertJsonEqual(
  optionalLegacyTranslationSource(" legacy-upload-1 "),
  { legacy_translation_upload_id: "legacy-upload-1" },
  "legacy upload id",
);
assertJsonEqual(
  optionalLegacyTranslationSource(""),
  {},
  "legacy upload omitted by default",
);
assertJsonEqual(
  normalizeOutputModes(["dual", "bilingual_overlay", "dual", "unsupported"]),
  ["dual", "bilingual_overlay"],
  "output mode validation and de-duplication",
);
assertJsonEqual(
  optionalRenderOutputModes([]),
  {},
  "output modes omitted by default",
);
assertJsonEqual(
  optionalRenderOutputModes(["bilingual_overlay", "dual"]),
  { output_modes: ["bilingual_overlay", "dual"] },
  "engineering drawing output modes",
);

console.log("engineering drawing payload smoke passed");
