import { NextRequest, NextResponse } from "next/server";

export async function middleware(req: NextRequest) {
  const password = process.env.WORKSPACE_PASSWORD;
  if (!password) {
    if (process.env.WORKSPACE_MODE === "standalone")
      return new NextResponse("WORKSPACE_PASSWORD 설정이 필요합니다.", { status: 503 });
    return NextResponse.next();
  }
  const expected = "Basic " + btoa("workspace:" + password);
  const encoder = new TextEncoder();
  const digest = (value: string) => crypto.subtle.digest("SHA-256", encoder.encode(value));
  const [a, b] = await Promise.all([digest(req.headers.get("authorization") ?? ""), digest(expected)]);
  const left = new Uint8Array(a), right = new Uint8Array(b);
  let difference = 0;
  for (let i = 0; i < left.length; i++) difference |= left[i] ^ right[i];
  if (difference !== 0) return new NextResponse("인증이 필요합니다.", {
    status: 401, headers: { "WWW-Authenticate": 'Basic realm="Meeting workspace", charset="UTF-8"' },
  });
  return NextResponse.next();
}
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
