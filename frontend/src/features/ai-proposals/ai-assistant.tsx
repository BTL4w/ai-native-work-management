"use client";

// Compatibility boundary for callers that still import the Phase 2 Assistant
// from the planning feature. The conversation-first shell owns the UI now.
export { AssistantShell as AiAssistant } from "@/features/assistant/assistant-shell";
