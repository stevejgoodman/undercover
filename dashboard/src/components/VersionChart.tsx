import type { Round, Scores } from "../api";
import { percent } from "../format";

interface Point {
  version: number;
  scores: Scores;
  kept: boolean | null;
}

// Each version the rounds measured on the held-out set, oldest first: the one a
// round started from, and the one it tried, with its verdict. Each tried version
// was tried from the one before it was kept, so the points aren't joined.
function versionsTried(rounds: Round[]): Point[] {
  const points = new Map<number, Point>();
  for (const round of [...rounds].reverse()) {
    if (round.scores_before && !points.has(round.version_before))
      points.set(round.version_before, {
        version: round.version_before,
        scores: round.scores_before,
        kept: null,
      });
    if (round.version_tried !== null && round.scores_after)
      points.set(round.version_tried, {
        version: round.version_tried,
        scores: round.scores_after,
        kept: round.verdict === "kept",
      });
  }
  return [...points.values()];
}

// How a version is marked: where a round started, or its verdict.
function dot(kept: boolean | null): string {
  if (kept === null) return "start";
  return kept ? "kept" : "rolled_back";
}

const WIDTH = 520;
const HEIGHT = 170;
const LEFT = 44;
const RIGHT = 16;
const TOP = 28;
const BOTTOM = 30;

function Panel({
  title,
  points,
  read,
  top,
  floor,
  show,
}: Readonly<{
  title: string;
  points: Point[];
  read: (scores: Scores) => number | null;
  top: number;
  floor: number;
  show: (value: number) => string;
}>) {
  const x = (index: number) =>
    LEFT +
    (points.length === 1
      ? (WIDTH - LEFT - RIGHT) / 2
      : (index * (WIDTH - LEFT - RIGHT)) / (points.length - 1));
  const y = (value: number) =>
    TOP + (1 - value / top) * (HEIGHT - TOP - BOTTOM);
  const shown = points.flatMap((point, index) => {
    const value = read(point.scores);
    return value === null ? [] : [{ point, index, value }];
  });
  const summary = shown
    .map(
      ({ point, value }) => `version ${String(point.version)} ${show(value)}`,
    )
    .join(", ");

  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <svg
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        role="img"
        aria-label={`${title}: ${summary}`}
      >
        {[0, top / 2, top].map((tick) => (
          <g key={tick}>
            <line
              className="chart-grid"
              x1={LEFT}
              x2={WIDTH - RIGHT}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text className="chart-axis" x={LEFT - 8} y={y(tick) + 4}>
              {show(tick)}
            </text>
          </g>
        ))}
        <line
          className="chart-floor"
          x1={LEFT}
          x2={WIDTH - RIGHT}
          y1={y(floor)}
          y2={y(floor)}
        />
        {shown.map(({ point, index, value }) => (
          <g key={point.version}>
            <circle
              className={`chart-dot chart-${dot(point.kept)}`}
              cx={x(index)}
              cy={y(value)}
              r={6}
            />
            <text className="chart-value" x={x(index)} y={y(value) - 11}>
              {show(value)}
            </text>
            <text className="chart-label" x={x(index)} y={HEIGHT - BOTTOM + 18}>
              v{point.version}
            </text>
          </g>
        ))}
      </svg>
    </figure>
  );
}

export function VersionChart({
  rounds,
  floors,
}: Readonly<{ rounds: Round[]; floors: { accuracy: number; grade: number } }>) {
  const points = versionsTried(rounds);
  if (points.length === 0)
    return (
      <p className="muted">
        No version has been measured yet. Each round's versions appear here once
        their held-out evaluations finish.
      </p>
    );
  return (
    <>
      <div className="charts">
        <Panel
          title="Held-out accuracy"
          points={points}
          read={(scores) => scores.accuracy}
          top={1}
          floor={floors.accuracy}
          show={percent}
        />
        <Panel
          title="Held-out grade"
          points={points}
          read={(scores) => scores.grade}
          top={3}
          floor={floors.grade}
          show={(value) => value.toFixed(2)}
        />
      </div>
      <p className="chart-key small muted">
        <span className="key key-start" /> The version a round started from{" "}
        <span className="key key-kept" /> Kept{" "}
        <span className="key key-rolled_back" /> Rolled back{" "}
        <span className="key key-floor" /> The business's floor
      </p>
    </>
  );
}
