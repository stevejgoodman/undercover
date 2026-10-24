import { useCallback, useState } from "react";
import { type AgentVersion, type VersionSummary, api } from "../api";
import { VerdictChip } from "../components/Chips";
import { DiffView } from "../components/DiffView";
import { Message } from "../components/Message";
import { PageHeader } from "../components/PageHeader";
import { NONE_YET, dateTime, grade, percent } from "../format";
import { useLoad } from "../useLoad";

export function ConfigurationPage() {
  const { data: versions, error } = useLoad(api.listVersions);
  const [shown, setShown] = useState<number>();
  const current = versions?.find((version) => version.current);

  return (
    <>
      <PageHeader
        title="Configuration"
        lead="The claim agent's instructions, model and reasoning effort, kept in versions. Every dispatch uses the current version. A new version comes only from a round of improvement that a senior handler approved."
      />
      <div className="column">
        {!versions && <Message error={error} />}
        {current && <CurrentVersion version={current} />}
        {versions && (
          <Versions versions={versions} shown={shown} onShow={setShown} />
        )}
        {shown !== undefined && <VersionChanges key={shown} version={shown} />}
      </div>
    </>
  );
}

function CurrentVersion({ version }: Readonly<{ version: AgentVersion }>) {
  return (
    <section className="panel" aria-labelledby="current-title">
      <h2 id="current-title">Current version: {version.version}</h2>
      <dl className="facts">
        <div>
          <dt>Model</dt>
          <dd className="mono">{version.model}</dd>
        </div>
        <div>
          <dt>Reasoning effort</dt>
          <dd>{version.reasoning_effort}</dd>
        </div>
        <div>
          <dt>Proposed by</dt>
          <dd>{version.proposed_by}</dd>
        </div>
        <div>
          <dt>Approved by</dt>
          <dd>
            {version.approved_by}, {dateTime(version.approved_at)}
          </dd>
        </div>
      </dl>
      <p className="reason">{version.reason}</p>
      <details className="instructions-details">
        <summary>Instructions</summary>
        <pre className="instructions">{version.instructions}</pre>
      </details>
      <p className="muted small">
        The claim agent also reads the contents of the policy wording and the
        claims manual after these instructions.
      </p>
    </section>
  );
}

function Versions({
  versions,
  shown,
  onShow,
}: Readonly<{
  versions: VersionSummary[];
  shown?: number;
  onShow: (version: number) => void;
}>) {
  return (
    <section className="panel" aria-labelledby="versions-title">
      <h2 id="versions-title">Versions</h2>
      <p className="muted small">
        Scores are the averages of the whole-set evaluations that rounds ran on
        each version. A version with none yet shows a dash.
      </p>
      <div className="table-scroll">
        <table className="table versions">
          <thead>
            <tr>
              <th>Version</th>
              <th>Model</th>
              <th>Change</th>
              <th>Status</th>
              <th className="num">Held-out accuracy</th>
              <th className="num">Held-out grade</th>
              <th>Approved by</th>
              <th>
                <span className="visually-hidden">Changes</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {versions.map((version) => (
              <tr key={version.version}>
                <td className="mono">{version.version}</td>
                <td>
                  <span className="mono">{version.model}</span>
                  <p className="muted small">
                    Reasoning effort {version.reasoning_effort}
                  </p>
                </td>
                <td>
                  {version.change}
                  <p className="muted small">{version.reason}</p>
                </td>
                <td>
                  <VerdictChip
                    verdict={version.verdict}
                    current={version.current}
                  />
                </td>
                <td className="num mono">
                  {version.scores.held_out
                    ? percent(version.scores.held_out.accuracy)
                    : NONE_YET}
                </td>
                <td className="num mono">
                  {version.scores.held_out
                    ? grade(version.scores.held_out.grade)
                    : NONE_YET}
                </td>
                <td>
                  {version.approved_by}
                  <p className="muted small">{dateTime(version.approved_at)}</p>
                </td>
                <td>
                  <button
                    type="button"
                    className="button secondary small-button"
                    aria-pressed={shown === version.version}
                    onClick={() => {
                      onShow(version.version);
                    }}
                  >
                    Show changes
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function VersionChanges({ version }: Readonly<{ version: number }>) {
  const load = useCallback(() => api.getVersion(version), [version]);
  const { data, error } = useLoad(load);

  return (
    <section className="panel" aria-labelledby="changes-title">
      <h2 id="changes-title">What version {version} changed</h2>
      {!data && <Message error={error} />}
      {data?.version === 1 && (
        <p className="muted">
          Version 1 is the first version, so there is nothing before it to
          compare with.
        </p>
      )}
      {data && data.version > 1 && (
        <>
          <p>
            {data.change}. <span className="muted">{data.reason}</span>
          </p>
          <DiffView
            lines={data.diff}
            label={`Changes to the instructions in version ${String(version)}`}
          />
        </>
      )}
    </section>
  );
}
