import { ApiError } from "../api";

export const TRY_AGAIN =
  "Try reloading the page. If this goes on, ask the platform team to check the backend is running.";

// What a page shows until its data arrives: that it's loading, that it wasn't
// found, when that's given, or why it failed.
export function Message({
  error,
  notFound,
}: Readonly<{ error?: Error; notFound?: string }>) {
  if (notFound && error instanceof ApiError && error.status === 404)
    return (
      <p className="message" role="status">
        {notFound}
      </p>
    );
  if (!error)
    return (
      <div className="skeleton" role="status">
        <span className="visually-hidden">Loading…</span>
        <span />
        <span />
        <span />
      </div>
    );
  return (
    <div className="message">
      <p role="alert">{error.message}</p>
      <p className="small">{TRY_AGAIN}</p>
    </div>
  );
}
