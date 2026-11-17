import assert from "node:assert/strict";
import test from "node:test";

import { commentLabelForSource } from "../src/commentLabel.js";

test("manual agent comments are labeled Agent", () => {
  assert.equal(commentLabelForSource("agent"), "Agent");
});

test("Gemini-generated comments are labeled AI", () => {
  assert.equal(commentLabelForSource("gemini"), "AI");
});

test("fallback-generated comments are labeled AI (Fallback)", () => {
  assert.equal(commentLabelForSource("fallback"), "AI (Fallback)");
});
