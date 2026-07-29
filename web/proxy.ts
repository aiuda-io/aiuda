import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Headers de seguridad para toda respuesta de la consola. Conservadores a
// propósito: nada que rompa Next (sin CSP estricta todavía). HSTS solo aplica
// sobre https; los navegadores lo ignoran en http (dev).
function harden(response: NextResponse): NextResponse {
  response.headers.set("X-Frame-Options", "DENY"); // la consola no se embebe en iframes
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), interest-cohort=()",
  );
  response.headers.set(
    "Strict-Transport-Security",
    "max-age=31536000; includeSubDomains",
  );
  return response;
}

// Sin login wall: la consola corre local (127.0.0.1) y el aislamiento vive en
// el bind del API + token de sesión por arranque. Aquí solo endurecemos headers.
export function proxy(_request: NextRequest) {
  return harden(NextResponse.next());
}

export const config = {
  // Todo menos assets estáticos y archivos públicos
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg|brand/|.*\\.svg$).*)"],
};
