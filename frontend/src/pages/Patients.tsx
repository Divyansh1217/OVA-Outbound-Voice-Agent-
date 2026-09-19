import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { patientService } from "../services/patients";
import type { Patient } from "../types";

export default function Patients() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    patientService
      .list()
      .then(setPatients)
      .catch((e) => setError(e.message));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return patients;
    return patients.filter(
      (p) => p.name.toLowerCase().includes(q) || p.phone.includes(q)
    );
  }, [patients, query]);

  if (error) return <div className="error">{error}</div>;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Patients</h1>
          <p className="page-sub">Patients with lab reports, ready for outreach calls.</p>
        </div>
        <Link to="/patients/new" className="btn btn-primary">
          + Add Patient
        </Link>
      </div>

      <div className="card">
        <input
          className="input"
          style={{ width: "100%", marginBottom: 14 }}
          placeholder="Search by name or phone…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {filtered.length === 0 ? (
          <div className="empty-state">
            {patients.length === 0
              ? "No patients yet. Create the first one to start arranging calls."
              : "No patients match your search."}
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>Biomarkers</th>
                <th>Last call</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => {
                return (
                  <tr key={p.id} className="row-link">
                    <td>
                      <Link to={`/patients/${p.id}`}>{p.name}</Link>
                    </td>
                    <td>{p.phone}</td>
                    <td>{p.biomarker_count ?? p.biomarkers.length}</td>
                    <td className="muted">{p.last_call_status ?? "—"}</td>
                    <td>
                      <Link to={`/patients/${p.id}`}>View</Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}