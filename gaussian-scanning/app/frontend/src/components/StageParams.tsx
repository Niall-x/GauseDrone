// Advanced settings for each stage, rendered from the backend's stage
// definitions so a new stage parameter needs no frontend change.
import type { StageConfig, StageDef } from "../api/client";
import { Field, Input, Select } from "./ui";

export function StageParams({
  stages,
  config,
  onChange,
  disabledStages = [],
}: {
  stages: StageDef[];
  config: StageConfig;
  onChange: (stage: string, param: string, value: unknown) => void;
  disabledStages?: string[];
}) {
  return (
    <div className="space-y-6">
      {stages
        .filter((s) => s.params.length)
        .map((stage) => {
          const disabled = disabledStages.includes(stage.name);
          return (
            <fieldset key={stage.name} disabled={disabled} className={disabled ? "opacity-50" : ""}>
              <legend className="mb-3 text-xs font-semibold uppercase tracking-wide text-faint">
                {stage.label}
                {disabled && <span className="ml-2 normal-case tracking-normal">(reused)</span>}
              </legend>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {stage.params.map((p) => {
                  const id = `${stage.name}-${p.name}`;
                  const value = config[stage.name]?.[p.name] ?? p.default;
                  return (
                    <Field key={p.name} label={p.label} help={p.help} htmlFor={id}>
                      {p.type === "choice" ? (
                        <Select id={id} value={String(value)} onChange={(e) => onChange(stage.name, p.name, e.target.value)}>
                          {p.choices!.map((c) => (
                            <option key={String(c)} value={String(c)}>
                              {String(c)}
                            </option>
                          ))}
                        </Select>
                      ) : (
                        <Input
                          id={id}
                          type="number"
                          value={String(value)}
                          min={p.min ?? undefined}
                          max={p.max ?? undefined}
                          step={p.type === "float" ? "any" : 1}
                          onChange={(e) => onChange(stage.name, p.name, e.target.value)}
                          className="font-mono"
                        />
                      )}
                    </Field>
                  );
                })}
              </div>
            </fieldset>
          );
        })}
    </div>
  );
}

/** Values that differ from the stage defaults, for sending as overrides. */
export function diffFromDefaults(stages: StageDef[], config: StageConfig): StageConfig {
  const out: StageConfig = {};
  for (const s of stages) {
    for (const p of s.params) {
      const v = config[s.name]?.[p.name];
      if (v !== undefined && String(v) !== String(p.default)) (out[s.name] ??= {})[p.name] = v;
    }
  }
  return out;
}

export function configFrom(stages: StageDef[], ...layers: (StageConfig | undefined)[]): StageConfig {
  const cfg: StageConfig = {};
  for (const s of stages) cfg[s.name] = Object.fromEntries(s.params.map((p) => [p.name, p.default]));
  for (const layer of layers)
    for (const [stage, values] of Object.entries(layer ?? {})) cfg[stage] = { ...cfg[stage], ...values };
  return cfg;
}
