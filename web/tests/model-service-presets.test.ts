import { expect, it } from "vitest";
import { servicePresets, applyPreset, newProfile } from "../src/settings/service-presets";
it("starts provider-neutral and optional presets preserve models and credentials", () => {
  expect(newProfile()).toMatchObject({ protocol: "openai-compatible", base_url: "", default_model: "" });
  const profile = { ...newProfile(), id: "lab", default_model: "chosen", credential_ref: "env:LAB_KEY", models: ["chosen"] };
  for (const preset of servicePresets) expect(applyPreset(profile, preset)).toMatchObject({ id: "lab", default_model: "chosen", credential_ref: "env:LAB_KEY", models: ["chosen"] });
  expect(servicePresets.find(p => p.id === "anthropic")!.base_url).toBe("https://api.anthropic.com/v1");
});
