import type { DiffLine } from "../api";

// Unchanged lines kept around each change; longer runs of them are folded.
const CONTEXT = 2;
const SIGNS = { added: "+", removed: "-", unchanged: " " } as const;

type Shown = DiffLine | { change: "folded"; count: number };

function fold(lines: DiffLine[]): Shown[] {
  const near = lines.map((_, at) =>
    lines
      .slice(Math.max(0, at - CONTEXT), at + CONTEXT + 1)
      .some((line) => line.change !== "unchanged"),
  );
  const shown: Shown[] = [];
  lines.forEach((line, at) => {
    if (near[at]) {
      shown.push(line);
      return;
    }
    const last = shown.at(-1);
    if (last?.change === "folded") last.count += 1;
    else shown.push({ change: "folded", count: 1 });
  });
  return shown;
}

// The lines a version or a recipe changed, added in green and removed in red,
// each with a plus or a minus too, so the color is never the only sign.
export function DiffView({
  lines,
  label,
}: Readonly<{ lines: DiffLine[]; label: string }>) {
  if (!lines.some((line) => line.change !== "unchanged"))
    return <p className="muted">No change to the text.</p>;
  return (
    <div className="diff" role="group" aria-label={label}>
      {fold(lines).map((line, at) =>
        line.change === "folded" ? (
          <div key={at} className="diff-line diff-folded">
            {line.count} unchanged {line.count === 1 ? "line" : "lines"}
          </div>
        ) : (
          <div key={at} className={`diff-line diff-${line.change}`}>
            <span className="diff-sign" aria-hidden="true">
              {SIGNS[line.change]}
            </span>
            <span className="visually-hidden">
              {line.change === "unchanged" ? "" : `${line.change}: `}
            </span>
            {line.text || " "}
          </div>
        ),
      )}
    </div>
  );
}
