import { Component, type ErrorInfo, type ReactNode } from "react";

import { logger } from "../services/logger";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    logger.error("ui_render_failed", {
      error: error.message,
      componentStack: info.componentStack,
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div role="alert">
          <h1>Something went wrong.</h1>
          <p>Reload the page to try again.</p>
        </div>
      );
    }
    return this.props.children;
  }
}
