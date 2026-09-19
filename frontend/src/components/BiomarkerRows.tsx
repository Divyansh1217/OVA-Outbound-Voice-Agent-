import type { BiomarkerInput } from "../services/patients";
import { inferStatus } from "../utils";

const STATUS_OPTIONS = ["NORMAL", "HIGH", "LOW", "BORDERLINE HIGH", "CRITICAL"];

interface Props {
  value: BiomarkerInput[];
  onChange: (rows: BiomarkerInput[]) => void;
}

function emptyRow(): BiomarkerInput {
  return { name: "", value: "", unit: "", reference_range: "", status: "NORMAL" };
}

export default function BiomarkerRows({ value, onChange }: Props) {
  const update = (index: number, patch: Partial<BiomarkerInput>) => {
    const rows = value.map((r, i) => (i === index ? { ...r, ...patch } : r));
    onChange(rows);
  };

  const updateWithInfer = (index: number, patch: Partial<BiomarkerInput>) => {
    const merged = { ...value[index], ...patch };
    if (patch.value !== undefined || patch.reference_range !== undefined) {
      const inferred = inferStatus(merged.value, merged.reference_range);
      if (inferred) merged.status = inferred;
    }
    const rows = value.map((r, i) => (i === index ? merged : r));
    onChange(rows);
  };

  return (
    <div>
      <table className="bio-table">
        <thead>
          <tr>
            <th style={{ width: "24%" }}>Biomarker</th>
            <th style={{ width: "15%" }}>Value</th>
            <th style={{ width: "12%" }}>Unit</th>
            <th style={{ width: "26%" }}>Reference Range</th>
            <th style={{ width: "15%" }}>Status</th>
            <th style={{ width: "8%" }}></th>
          </tr>
        </thead>
        <tbody>
          {value.map((row, i) => (
            <tr key={i}>
              <td>
                <input
                  className="input"
                  placeholder="e.g. HbA1c"
                  value={row.name}
                  onChange={(e) => update(i, { name: e.target.value })}
                />
              </td>
              <td>
                <input
                  className="input"
                  placeholder="e.g. 7.8"
                  value={row.value}
                  onChange={(e) => updateWithInfer(i, { value: e.target.value })}
                />
              </td>
              <td>
                <input
                  className="input"
                  placeholder="%"
                  value={row.unit}
                  onChange={(e) => update(i, { unit: e.target.value })}
                />
              </td>
              <td>
                <input
                  className="input"
                  placeholder="<5.7% or 70-100 mg/dL"
                  value={row.reference_range}
                  onChange={(e) => updateWithInfer(i, { reference_range: e.target.value })}
                />
              </td>
              <td>
                <select
                  className="select"
                  value={row.status}
                  onChange={(e) => update(i, { status: e.target.value })}
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  onClick={() => onChange(value.filter((_, j) => j !== i))}
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        style={{ marginTop: 10 }}
        onClick={() => onChange([...value, emptyRow()])}
      >
        + Add biomarker
      </button>
    </div>
  );
}