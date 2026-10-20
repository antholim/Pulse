import { ApiError } from "./api";

const FRIENDLY_MESSAGES: Record<string, string> = {
  network_error: "We can't reach the PULSE server. Check your connection and try again.",
  internal_error: "Something went wrong on our side. Please try again in a moment.",
  service_unavailable: "PULSE is temporarily unavailable. Please try again in a moment.",
};

export function toUserMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "http_error" && error.status !== null && error.status >= 500) {
      return FRIENDLY_MESSAGES.internal_error;
    }
    return FRIENDLY_MESSAGES[error.code] ?? error.message;
  }
  return "Something went wrong. Please try again.";
}
