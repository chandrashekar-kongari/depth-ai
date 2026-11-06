import useSWR from "swr";
import type { EngineeringReview } from "@/lib/engineering/types";

async function fetchReview(url: string): Promise<EngineeringReview> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

async function fetchReviews(url: string): Promise<EngineeringReview[]> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

export function useEngineeringReviews() {
  return useSWR<EngineeringReview[]>("/api/engineering/reviews", fetchReviews, {
    refreshInterval: 5000,
  });
}

export function useEngineeringReview(id: string | null) {
  return useSWR<EngineeringReview>(
    id ? `/api/engineering/reviews/${id}` : null,
    fetchReview,
    {
      refreshInterval: (data) =>
        data?.status === "queued" || data?.status === "running" ? 2000 : 0,
    }
  );
}

async function fetchAvailability(url: string): Promise<{ enabled: boolean }> {
  const response = await fetch(url);
  if (!response.ok) return { enabled: false };
  return response.json();
}

export function useReviewAvailability() {
  return useSWR<{ enabled: boolean }>(
    "/api/engineering/reviews/capabilities",
    fetchAvailability
  );
}
