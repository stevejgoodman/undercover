import { useState } from "react";
import { type AllowedModel, api } from "../api";
import {
  type Appearance,
  appearances,
  applyAppearance,
  storedAppearance,
} from "../appearance";
import { Message } from "../components/Message";
import { PageHeader } from "../components/PageHeader";
import { SettingsForm } from "../components/SettingsForm";
import { money } from "../format";
import { useLoad } from "../useLoad";

export function SettingsPage() {
  const { data, error, reload } = useLoad(api.getSettings);
  const { data: models, error: modelsError } = useLoad(api.listModels);

  return (
    <>
      <PageHeader
        title="Settings"
        lead="The business's numbers that every part of the platform works to. Every handler can see them; a senior handler can change them, and each change is kept on record."
      />
      <div className="column">
        {!data && <Message error={error} />}
        {data && (
          <SettingsForm
            key={data.changes.length}
            current={data.current}
            changes={data.changes}
            onSaved={reload}
          />
        )}
        <section className="panel" aria-labelledby="models-title">
          <h2 id="models-title">Models allowed</h2>
          <p className="muted small">
            The models the claim agent may use, set in{" "}
            <span className="mono">data/models.json</span>. They can't be
            changed here.
          </p>
          {models ? (
            <ModelsTable models={models} />
          ) : (
            <Message error={modelsError} />
          )}
        </section>
        <AppearanceChoice />
      </div>
    </>
  );
}

function ModelsTable({ models }: Readonly<{ models: AllowedModel[] }>) {
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Model</th>
            <th>Reasoning efforts</th>
            <th className="num">Input price</th>
            <th className="num">Output price</th>
          </tr>
        </thead>
        <tbody>
          {models.map((model) => (
            <tr key={model.model}>
              <td className="mono">{model.model}</td>
              <td>{model.reasoning_efforts.join(", ")}</td>
              <td className="num mono">
                {money(model.input_price)} per million tokens
              </td>
              <td className="num mono">
                {money(model.output_price)} per million tokens
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const APPEARANCE_LABELS: Record<Appearance, string> = {
  light: "Light",
  dark: "Dark",
  system: "Same as the computer",
};

function AppearanceChoice() {
  const [appearance, setAppearance] = useState(storedAppearance);

  return (
    <section className="panel" aria-labelledby="appearance-title">
      <h2 id="appearance-title">Appearance</h2>
      <p className="muted small">This browser remembers your choice.</p>
      <div className="segmented" role="radiogroup" aria-label="Appearance">
        {appearances.map((choice) => (
          <label key={choice} className="segment">
            <input
              type="radio"
              name="appearance"
              checked={appearance === choice}
              onChange={() => {
                applyAppearance(choice);
                setAppearance(choice);
              }}
            />
            {APPEARANCE_LABELS[choice]}
          </label>
        ))}
      </div>
    </section>
  );
}
