import type { Biomarker } from "../types";
import { statusBadgeClass } from "../utils";

export default function BiomarkerTable({ biomarkers }: { biomarkers: Biomarker[] }) {
  if (!biomarkers.length) {
    return <p className="muted">No report added yet.</p>;
  }
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Biomarker</th>
          <th>Value</th>
          <th>Unit</th>
          <th>Reference Range</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {biomarkers.map((b, i) => (
          <tr key={i}>
            <td>{b.name}</td>
            <td>{b.value}</td>
            <td>{b.unit}</td>
            <td>{b.reference_range || "—"}</td>
            <td>
              <span className={`badge ${statusBadgeClass(b.status)}`}>{b.status}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}