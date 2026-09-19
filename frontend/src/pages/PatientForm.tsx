import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import BiomarkerRows from "../components/BiomarkerRows";
import { patientService, type BiomarkerInput } from "../services/patients";
import type { Patient } from "../types";

const isNewRoute = (id: string | undefined) => id === "new" || id === undefined;

export default function PatientForm() {
  const params = useParams();
  const navigate = useNavigate();
  const editingId = isNewRoute(params.id) ? null : params.id!;

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");
  const [biomarkers, setBiomarkers] = useState<BiomarkerInput[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!editingId) return;
    patientService
      .get(editingId)
      .then((p: Patient) => {
        setName(p.name);
        setPhone(p.phone);
        setNotes(p.notes);
        setBiomarkers(p.biomarkers.map((b) => ({ ...b })));
      })
      .catch((e) => setError(e.message));
  }, [editingId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      let patient: Patient;
      if (editingId) {
        patient = await patientService.update(
          editingId,
          { name, phone, notes }
        );
      } else {
        patient = await patientService.create({ name, phone, notes });
      }
      await patientService.saveReport(patient.id, biomarkers);
      navigate(`/patients/${patient.id}`);
    } catch (err) {
      setError((err as Error).message);
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{editingId ? "Edit Patient" : "New Patient"}</h1>
          <p className="page-sub">
            Patient details plus their lab report. The report is what the voice agent
            discusses on the call.
          </p>
        </div>
      </div>

      <form onSubmit={submit}>
        <div className="card">
          <h2 className="card-title">Patient</h2>
          <div className="form-grid">
            <div className="form-group">
              <label className="label">Full name</label>
              <input
                className="input"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Sarah Johnson"
              />
            </div>
            <div className="form-group">
              <label className="label">Phone number</label>
              <input
                className="input"
                required
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="e.g. +15550123456"
              />
            </div>
            <div className="form-group full">
              <label className="label">Notes</label>
              <textarea
                className="textarea"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Extra context for the care team (optional)"
              />
            </div>
          </div>
        </div>

        <div className="card">
          <h2 className="card-title">Lab report (biomarkers)</h2>
          <BiomarkerRows value={biomarkers} onChange={setBiomarkers} />
        </div>

        {error && <div className="error">{error}</div>}

        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? "Saving…" : editingId ? "Save changes" : "Create patient"}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => navigate(-1)}
          >
            Cancel
          </button>
        </div>
      </form>
    </>
  );
}