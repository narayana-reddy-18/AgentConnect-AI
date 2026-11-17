export function commentLabelForSource(source) {
  if (source === "gemini") return "AI";
  if (source === "fallback") return "AI (Fallback)";
  return "Agent";
}
