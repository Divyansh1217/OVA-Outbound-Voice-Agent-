import { request } from "./api";
import type { Call, DashboardStats } from "../types";

export const callService = {
  list: () => request<{ calls: Call[]; stats: DashboardStats }>("/calls"),

  get: (id: string) => request<Call>(`/calls/${id}`),

  arrange: (patientId: string, preferredTime: string) =>
    request<Call>("/calls", {
      method: "POST",
      body: JSON.stringify({ patient_id: patientId, preferred_time: preferredTime }),
    }),
};