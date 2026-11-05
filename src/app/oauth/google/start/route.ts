import { NextResponse } from "next/server";

import { getSettings } from "@/lib/config";
import { GOOGLE_SCOPES } from "@/lib/google";
import { requireUser } from "@/lib/http";
import { makeOauthState } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const denied = await requireUser();
  if (denied) return denied;
  const settings = getSettings();
  if (!settings.googleClientId || !settings.googleOauthRedirectUri) {
    return new NextResponse("Set GOOGLE_CLIENT_ID and GOOGLE_OAUTH_REDIRECT_URI before connecting Google.", { status: 400 });
  }
  const params = new URLSearchParams({
    client_id: settings.googleClientId,
    redirect_uri: settings.googleOauthRedirectUri,
    response_type: "code",
    scope: GOOGLE_SCOPES.join(" "),
    access_type: "offline",
    prompt: "consent",
    include_granted_scopes: "true",
    state: makeOauthState(settings.appSecretKey),
  });
  return NextResponse.redirect(`https://accounts.google.com/o/oauth2/v2/auth?${params}`);
}
