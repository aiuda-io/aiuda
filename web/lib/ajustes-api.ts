// Lo que Ajustes y el asistente de primer arranque le piden al servidor y todavía no
// vive en lib/api.ts. Mismo origen, misma llave opcional, mismo aviso de escritura.

import { ApiError, apiUrl } from "@/lib/api";

const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

async function pedir<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: {
      ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    const detalle = await res.json().catch(() => null);
    throw new ApiError(
      typeof detalle?.detail === "string"
        ? detalle.detail
        : "aiuda no pudo completar esto. Intenta de nuevo.",
      res.status,
      typeof detalle?.code === "string" ? detalle.code : undefined,
    );
  }
  if (init?.method && init.method !== "GET" && typeof window !== "undefined") {
    window.dispatchEvent(new Event("aiuda-escritura"));
  }
  return res.json() as Promise<T>;
}

/** Modo de prueba. `retenidos` = lo aprobado que no ha salido: lo que se iría a
 *  clientes reales al apagarlo. */
export type ModoPrueba = { modo_sombra: boolean; retenidos: number };

export type ModoPruebaCambio = ModoPrueba & {
  retenidos_accion: "enviando" | "no_enviados" | null;
};

export const ajustesApi = {
  modoPrueba: () => pedir<ModoPrueba>("/v1/settings/modo-sombra"),
  /** `retenidos` solo cuenta al apagar: mandar lo aprobado ya, o dejarlo en
   *  "No salió" para que no se vaya solo. */
  cambiarModoPrueba: (activo: boolean, retenidos?: "enviar" | "no_enviar") =>
    pedir<ModoPruebaCambio>("/v1/settings/modo-sombra", {
      method: "PUT",
      body: JSON.stringify({ activo, retenidos: retenidos ?? null }),
    }),
  /** El negocio y la versión de aiuda que corre en esta computadora. */
  instalacion: () =>
    pedir<{ business_name: string; role: string; version?: string }>("/v1/workspace"),
  /** ¿El negocio sigue en modo de prueba? Para el cierre del asistente. */
  setupModoPrueba: () =>
    pedir<{ modo_prueba?: boolean }>("/v1/setup/estado").then((e) => !!e.modo_prueba),
};

/** Las cuatro secciones de Ajustes, por query (`/configuracion?seccion=…`). */
export const SECCIONES = [
  { key: "negocio", label: "Negocio" },
  { key: "conexiones", label: "Conexiones" },
  { key: "ia", label: "Tu IA" },
  { key: "telefono", label: "Teléfono y equipo" },
] as const;

export type Seccion = (typeof SECCIONES)[number]["key"];

export function esSeccion(v: string | null): v is Seccion {
  return SECCIONES.some((s) => s.key === v);
}

/** La dirección de una sección de Ajustes. `abrir` deja abierto el panel de una
 *  conexión (solo tiene sentido en Conexiones). */
export function rutaAjustes(seccion: Seccion, abrir?: string): string {
  const q = new URLSearchParams();
  if (seccion !== "negocio") q.set("seccion", seccion);
  if (abrir) q.set("abrir", abrir);
  const cola = q.toString();
  return cola ? `/configuracion?${cola}` : "/configuracion";
}
