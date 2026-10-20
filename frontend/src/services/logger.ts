export type LogLevel = "debug" | "info" | "warn" | "error";
export type LogContext = Record<string, unknown>;

export interface Logger {
  debug(message: string, context?: LogContext): void;
  info(message: string, context?: LogContext): void;
  warn(message: string, context?: LogContext): void;
  error(message: string, context?: LogContext): void;
}

const LEVEL_ORDER: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };

function isLogLevel(value: string): value is LogLevel {
  return Object.hasOwn(LEVEL_ORDER, value);
}

export function resolveLogLevel(configured: string | undefined, isDev: boolean): LogLevel {
  const level = configured?.trim().toLowerCase();
  if (level && isLogLevel(level)) {
    return level;
  }
  return isDev ? "debug" : "warn";
}

export function createLogger(minLevel: LogLevel): Logger {
  const write =
    (level: LogLevel) =>
    (message: string, context: LogContext = {}) => {
      if (LEVEL_ORDER[level] < LEVEL_ORDER[minLevel]) {
        return;
      }
      console[level](`[PULSE] ${message}`, {
        timestamp: new Date().toISOString(),
        level,
        message,
        ...context,
      });
    };

  return { debug: write("debug"), info: write("info"), warn: write("warn"), error: write("error") };
}

export const logger = createLogger(
  resolveLogLevel(import.meta.env.VITE_LOG_LEVEL, import.meta.env.DEV),
);

export function installGlobalErrorLogging(target: EventTarget = window): void {
  target.addEventListener("error", (event) => {
    logger.error("uncaught_error", { error: (event as ErrorEvent).message });
  });
  target.addEventListener("unhandledrejection", (event) => {
    const reason: unknown = (event as PromiseRejectionEvent).reason;
    logger.error("unhandled_rejection", {
      error: reason instanceof Error ? reason.message : String(reason),
    });
  });
}
