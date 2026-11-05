import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { Dashboard } from "@/components/dashboard";
import { getSettings } from "@/lib/config";
import { readSession, SESSION_COOKIE } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  let settings;
  try {
    settings = getSettings();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Configuration failed";
    const host = process.env.VERCEL_PROJECT_PRODUCTION_URL || "your-app.vercel.app";
    return (
      <main className="sheet">
        <p className="brand">Synx</p>
        <h1>Back Office needs its settings</h1>
        <p className="lede">{message}</p>
        <p className="note">
          Add the variables from your local .env to the Vercel project, then redeploy.
          The Google redirect URI for this site is https://{host}/oauth/google/callback.
          Add that exact address on the Google OAuth client as well.
        </p>
      </main>
    );
  }
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!readSession(token, settings.appSecretKey)) redirect("/login");
  return <Dashboard appName={settings.appName} />;
}
