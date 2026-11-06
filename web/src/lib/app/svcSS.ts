import type { Metadata } from "next";
import { resolveApplicationDisplayName } from "@/lib/constants";
import { fetchEnterpriseSettingsSS } from "@/lib/settings/svcSS";

/** Server-side twin of useSettings().appName for server components. */
export async function fetchAppName(): Promise<string> {
  const enterprise = await fetchEnterpriseSettingsSS();
  return resolveApplicationDisplayName(enterprise?.application_name);
}

export async function generateFaviconMetadata(): Promise<Metadata["icons"]> {
  const enterprise = await fetchEnterpriseSettingsSS();
  if (enterprise?.use_custom_logo) {
    return { icon: "/api/enterprise-settings/logo" };
  }
  return {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", sizes: "32x32" },
    ],
  };
}

export async function generateAdminTitleMetadata(): Promise<Metadata["title"]> {
  return `Admin | ${await fetchAppName()}`;
}
