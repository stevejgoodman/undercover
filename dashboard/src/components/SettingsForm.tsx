import { useState } from "react";
import type { Limits, Settings, SettingsRequest } from "../api";
import { api } from "../api";
import { dateTime, money } from "../format";
import { seniorOnly } from "../permissions";
import { useHandler } from "../session";
import { useAction } from "../useAction";
import { ConfirmDialog } from "./ConfirmDialog";

type Measure = keyof Limits;

// How a number is shown and the range it may take, as the backend checks it.
// Percentages and points are shown times 100.
interface Range {
  scale?: number;
  min: number;
  max?: number;
  whole?: boolean;
}

interface Setting extends Range {
  label: string;
  unit: string;
  read: (settings: SettingsRequest) => number;
  write: (settings: SettingsRequest, value: number) => SettingsRequest;
}

const CENTS = 0.01;

// The settings with one value each.
const SETTINGS: Setting[] = [
  {
    label: "Approval limit",
    unit: "US dollars: a payout over it needs a handler's sign-off",
    min: CENTS,
    read: (s) => s.payout_approval_limit,
    write: (s, value) => ({ ...s, payout_approval_limit: value }),
  },
  {
    label: "Held-out accuracy floor",
    unit: "%",
    scale: 100,
    min: 0,
    max: 100,
    read: (s) => s.objectives.accuracy,
    write: (s, value) => ({
      ...s,
      objectives: { ...s.objectives, accuracy: value },
    }),
  },
  {
    label: "Grade floor",
    unit: "of 3, from F at 0 to A at 3",
    min: 0,
    max: 3,
    read: (s) => s.objectives.grade,
    write: (s, value) => ({
      ...s,
      objectives: { ...s.objectives, grade: value },
    }),
  },
  {
    label: "Spending limit for each round",
    unit: "US dollars",
    min: CENTS,
    read: (s) => s.spending_limit,
    write: (s, value) => ({ ...s, spending_limit: value }),
  },
  {
    label: "Claim agents at once in a round",
    unit: "from 1 to 25",
    min: 1,
    max: 25,
    whole: true,
    read: (s) => s.agents,
    write: (s, value) => ({ ...s, agents: value }),
  },
];

// The measures UnderCover's rule compares, with how their noise and tolerance
// are shown: points of accuracy and of the grade, and percentages of the old
// cost and time.
const MEASURES: (Range & { key: Measure; label: string; unit: string })[] = [
  {
    key: "accuracy",
    label: "Accuracy",
    unit: "points",
    scale: 100,
    min: 0,
    max: 100,
  },
  { key: "grade", label: "Grade", unit: "of 3", min: 0, max: 3 },
  {
    key: "model_cost_per_claim",
    label: "Model cost per claim",
    unit: "% of the old",
    scale: 100,
    min: 0,
  },
  {
    key: "seconds_per_claim",
    label: "Time per claim",
    unit: "% of the old",
    scale: 100,
    min: 0,
  },
];

const LIMITS = ["noise", "tolerance"] as const;

function editable(settings: Settings): SettingsRequest {
  return {
    payout_approval_limit: settings.payout_approval_limit,
    objectives: { ...settings.objectives },
    noise: { ...settings.noise },
    tolerance: { ...settings.tolerance },
    spending_limit: settings.spending_limit,
    agents: settings.agents,
  };
}

const shown = (value: number, scale = 1) => Number((value * scale).toFixed(4));

// Who last changed one setting, and when: the newest change that set it to
// what it is now.
function lastChange(
  changes: Settings[],
  read: (settings: Settings) => unknown,
): Settings {
  const value = JSON.stringify(read(changes[0]));
  const at = changes.findIndex(
    (_, index) =>
      index === changes.length - 1 ||
      JSON.stringify(read(changes[index + 1])) !== value,
  );
  return changes[at];
}

function ChangedBy({
  changes,
  read,
}: Readonly<{ changes: Settings[]; read: (settings: Settings) => unknown }>) {
  const change = lastChange(changes, read);
  return (
    <span className="muted small">
      {change.changed_by}, {dateTime(change.changed_at)}
    </span>
  );
}

// A number a senior handler can change, which reports null while what's typed
// isn't a number in its range. Anyone else sees the number alone.
function NumberField({
  label,
  value,
  range,
  editing,
  onChange,
}: Readonly<{
  label: string;
  value: number;
  range: Range;
  editing: boolean;
  onChange: (value: number | null) => void;
}>) {
  const scale = range.scale ?? 1;
  const [text, setText] = useState(String(shown(value, scale)));

  if (!editing) return <span className="mono">{shown(value, scale)}</span>;
  return (
    <input
      type="number"
      className="number-input mono"
      aria-label={label}
      min={range.min}
      max={range.max}
      step={range.whole ? 1 : "any"}
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        const number = event.target.valueAsNumber;
        const valid = event.target.checkValidity() && !Number.isNaN(number);
        onChange(valid ? number / scale : null);
      }}
    />
  );
}

export function SettingsForm({
  current,
  changes,
  onSaved,
}: Readonly<{ current: Settings; changes: Settings[]; onSaved: () => void }>) {
  const handler = useHandler();
  const senior = handler.can_approve_over_limit;
  const [draft, setDraft] = useState(() => editable(current));
  const [invalid, setInvalid] = useState<ReadonlySet<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const { run, sending, error } = useAction();
  const changed = JSON.stringify(draft) !== JSON.stringify(editable(current));
  const ready = changed && invalid.size === 0 && !sending;

  // Keeps a valid number in the draft, and remembers which fields aren't.
  function change(label: string, update: (value: number) => SettingsRequest) {
    return (value: number | null) => {
      const next = new Set(invalid);
      if (value === null) next.add(label);
      else {
        next.delete(label);
        setDraft(update(value));
      }
      setInvalid(next);
    };
  }

  return (
    <section className="panel" aria-labelledby="settings-title">
      <div className="panel-heading">
        <h2 id="settings-title">The platform's settings</h2>
        {senior && (
          <button
            type="button"
            className="button"
            aria-disabled={!ready}
            onClick={() => {
              if (ready) setConfirming(true);
            }}
          >
            Save changes
          </button>
        )}
      </div>
      {!senior && (
        <p className="notice" role="note">
          {seniorOnly(
            handler.name,
            current.payout_approval_limit,
            "change the settings",
          )}
        </p>
      )}
      {invalid.size > 0 && (
        <p className="form-error" role="alert">
          Check {[...invalid].join(", ")}: each must be a number in its range.
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <table className="table settings-table">
        <thead>
          <tr>
            <th>Setting</th>
            <th className="num">Value</th>
            <th>Unit</th>
            <th>Last changed</th>
          </tr>
        </thead>
        <tbody>
          {SETTINGS.map((setting) => (
            <tr key={setting.label}>
              <th scope="row">{setting.label}</th>
              <td className="num">
                <NumberField
                  label={setting.label}
                  value={setting.read(draft)}
                  range={setting}
                  editing={senior}
                  onChange={change(setting.label, (value) =>
                    setting.write(draft, value),
                  )}
                />
              </td>
              <td className="muted">{setting.unit}</td>
              <td>
                <ChangedBy changes={changes} read={setting.read} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className="subheading">Noise and tolerance</h3>
      <p className="muted small">
        A new version is kept when it meets the floors, at least one measure
        improves by more than its noise, and none gets worse by more than its
        tolerance.
      </p>
      <table className="table settings-table">
        <thead>
          <tr>
            <th>Measure</th>
            <th className="num">Noise</th>
            <th className="num">Tolerance</th>
            <th>Unit</th>
            <th>Last changed</th>
          </tr>
        </thead>
        <tbody>
          {MEASURES.map((measure) => (
            <tr key={measure.key}>
              <th scope="row">{measure.label}</th>
              {LIMITS.map((kind) => (
                <td className="num" key={kind}>
                  <NumberField
                    label={`${measure.label} ${kind}`}
                    value={draft[kind][measure.key]}
                    range={measure}
                    editing={senior}
                    onChange={change(`${measure.label} ${kind}`, (value) => ({
                      ...draft,
                      [kind]: { ...draft[kind], [measure.key]: value },
                    }))}
                  />
                </td>
              ))}
              <td className="muted">{measure.unit}</td>
              <td>
                <ChangedBy
                  changes={changes}
                  read={(s) => LIMITS.map((kind) => s[kind][measure.key])}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ConfirmDialog
        open={confirming}
        title="Save the settings?"
        confirmLabel="Save changes"
        onConfirm={() => {
          setConfirming(false);
          run(() => api.updateSettings(draft).then(onSaved));
        }}
        onCancel={() => {
          setConfirming(false);
        }}
      >
        <p>
          The new settings apply from now on, to decisions recorded and rounds
          started after the change. A round already open keeps the settings it
          started with. The approval limit will be{" "}
          <span className="mono">{money(draft.payout_approval_limit)}</span>.
        </p>
      </ConfirmDialog>
    </section>
  );
}
