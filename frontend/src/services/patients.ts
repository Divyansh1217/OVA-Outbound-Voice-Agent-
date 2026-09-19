import { request } from "./api";
import type { Patient } from "../types";

export interface PatientInput {
  name: string;
  phone: string;
  notes: string;
}

export interface BiomarkerInput {
  name: string;
  value: string;
  unit: string;
  reference_range: string;
  status: string;
}

export const patientService = {
  list: () => request<Patient[]>("/patients"),

  get: (id: string) => request<Patient>(`/patients/${id}`),

  create: (body: PatientInput) =>
    request<Patient>("/patients", { method: "POST", body: JSON.stringify(body) }),

  update: (id: string, body: Partial<PatientInput>) =>
    request<Patient>(`/patients/${id}`, { method: "PUT", body: JSON.stringify(body) }),

  remove: (id: string) => request<void>(`/patients/${id}`, { method: "DELETE" }),

  saveReport: (id: string, biomarkers: BiomarkerInput[]) =>
    request<Patient>(`/patients/${id}/report`, {
      method: "PUT",
      body: JSON.stringify({ biomarkers }),
    }),
};