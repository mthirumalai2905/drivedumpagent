import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { Dashboard } from "@/components/dashboard";
import { getSettings } from "@/lib/config";
import { readSession, SESSION_COOKIE } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const settings = getSettings();
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!readSession(token, settings.appSecretKey)) redirect("/login");
  return <Dashboard appName={settings.appName} />;
}
