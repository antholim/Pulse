import { ApiError } from "../services/api";
import { toUserMessage } from "../services/errors";

export function ErrorMessage({ error }: { error: unknown }) {
  const requestId = error instanceof ApiError ? error.requestId : null;

  return (
    <div role="alert">
      <p>{toUserMessage(error)}</p>
      {requestId && <p>Reference: {requestId}</p>}
    </div>
  );
}
