import type { RunDetails } from "../api";

export function ModelName({
  run,
}: Readonly<{
  run: Pick<RunDetails, "version" | "model" | "reasoning_effort">;
}>) {
  return (
    <>
      version {run.version}, <span className="mono">{run.model}</span>,
      reasoning effort {run.reasoning_effort}
    </>
  );
}
