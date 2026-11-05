import { NextResponse } from "next/server";

import { getSettings } from "@/lib/config";
import { createRootFolder } from "@/lib/google";
import { requireUser } from "@/lib/http";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = await requireUser();
  if (denied) return denied;
  const body = await request.json().catch(() => ({}));
  const name = String(body.name || "Back Office");
  try {
    const id = await createRootFolder(getSettings(), name);
    return NextResponse.json({
      id,
      detail: "Folder created. Set GOOGLE_DRIVE_FOLDER_ID to this id and restart.",
    });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Drive folder was not created" },
      { status: 502 },
    );
  }
}
