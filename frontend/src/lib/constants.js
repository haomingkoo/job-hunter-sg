import { Clock, CheckCircle, AlertCircle, X } from "lucide-react";

export const STATUS_CONFIG = {
  saved: { label: "Saved", color: "bg-gray-100 text-gray-600", icon: Clock, order: 0 },
  applied: { label: "Applied", color: "bg-blue-100 text-blue-800", icon: Clock, order: 1 },
  screening: { label: "Screening", color: "bg-indigo-100 text-indigo-800", icon: AlertCircle, order: 2 },
  interview: { label: "Interview", color: "bg-yellow-100 text-yellow-800", icon: AlertCircle, order: 3 },
  assessment: { label: "Assessment", color: "bg-orange-100 text-orange-800", icon: AlertCircle, order: 4 },
  final_round: { label: "Final Round", color: "bg-purple-100 text-purple-800", icon: AlertCircle, order: 5 },
  offer: { label: "Offer", color: "bg-green-100 text-green-800", icon: CheckCircle, order: 6 },
  accepted: { label: "Accepted", color: "bg-emerald-100 text-emerald-800", icon: CheckCircle, order: 7 },
  rejected: { label: "Rejected", color: "bg-red-100 text-red-700", icon: X, order: 8 },
  withdrawn: { label: "Withdrawn", color: "bg-gray-100 text-gray-600", icon: X, order: 9 },
  no_response: { label: "No Response", color: "bg-gray-100 text-gray-500", icon: Clock, order: 10 },
};

export const SG_JOB_PORTALS = [
  { name: "MyCareersFuture", key: "mcf", type: "api" },
  { name: "Careers@Gov", key: "careersgov", type: "api" },
  { name: "Adzuna", key: "adzuna", type: "api" },
  { name: "Jooble", key: "jooble", type: "api" },
  { name: "NodeFlair", key: "nodeflair", type: "scrape" },
  { name: "Indeed SG", key: "indeed", type: "scrape" },
  { name: "JobStreet", key: "jobstreet", type: "scrape" },
];
