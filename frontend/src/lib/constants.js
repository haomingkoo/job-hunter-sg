import { Clock, CheckCircle, AlertCircle, X } from "lucide-react";

export const STATUS_CONFIG = {
  saved: { label: "Saved", color: "bg-gray-100 text-gray-600", icon: Clock },
  applied: { label: "Applied", color: "bg-blue-100 text-blue-800", icon: Clock },
  screening: { label: "Screening", color: "bg-indigo-100 text-indigo-800", icon: AlertCircle },
  interview: { label: "Interview", color: "bg-yellow-100 text-yellow-800", icon: AlertCircle },
  assessment: { label: "Assessment", color: "bg-orange-100 text-orange-800", icon: AlertCircle },
  final_round: { label: "Final Round", color: "bg-purple-100 text-purple-800", icon: AlertCircle },
  offer: { label: "Offer", color: "bg-green-100 text-green-800", icon: CheckCircle },
  accepted: { label: "Accepted", color: "bg-emerald-100 text-emerald-800", icon: CheckCircle },
  rejected: { label: "Rejected", color: "bg-red-100 text-red-700", icon: X },
  withdrawn: { label: "Withdrawn", color: "bg-gray-100 text-gray-600", icon: X },
  no_response: { label: "No Response", color: "bg-gray-100 text-gray-500", icon: Clock },
};

export const SG_JOB_PORTALS = [
  { name: "MyCareersFuture", key: "mcf" },
  { name: "Careers@Gov", key: "careersgov" },
  { name: "Adzuna", key: "adzuna" },
  { name: "Jooble", key: "jooble" },
  { name: "NodeFlair", key: "nodeflair" },
  { name: "Indeed SG", key: "indeed" },
  { name: "JobStreet", key: "jobstreet" },
];
