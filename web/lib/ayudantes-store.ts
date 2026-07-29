"use client";

// Store de los ayudantes que el dueño crea y compone. Fase 2: la fuente de verdad
// vive en el backend (por-tenant), no en localStorage, porque el motor lee la config.
// Cache reactivo en cliente + suscriptores, para que la lista y el detalle se sincronicen
// sin recargar. Conserva la forma de los hooks anteriores (useAyudantes / useAyudante).
import { useEffect, useState } from "react";
import {
  api,
  type AiuditaConfig,
  type AiuditasCatalog,
  type AyudanteAppearance,
  type AyudanteDTO,
} from "@/lib/api";

export type Ayudante = AyudanteDTO;

// --- Cache de ayudantes -----------------------------------------------------

let cache: Ayudante[] | null = null;
let cacheError: string | null = null; // sin esto, un fetch fallido dejaba "Cargando…" eterno
let inflight: Promise<Ayudante[]> | null = null;
const subs = new Set<() => void>();

function notify() {
  for (const fn of subs) fn();
}

function load(): Promise<Ayudante[]> {
  if (inflight) return inflight;
  if (cacheError !== null) {
    cacheError = null;
    notify(); // reintento: vuelve a "cargando" de inmediato
  }
  inflight = api
    .ayudantes()
    .then((list) => {
      cache = list;
      notify();
      return list;
    })
    .catch((e: Error) => {
      cacheError = e.message || "No se pudo cargar a tu equipo.";
      notify();
      return [] as Ayudante[];
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

function replace(a: Ayudante) {
  cache = (cache ?? []).map((x) => (x.id === a.id ? a : x));
  notify();
}

/** Hook reactivo: la lista de ayudantes del tenant (la carga al montar).
 *  `error` + `retry`: si el fetch falla, la página lo dice y ofrece reintentar
 *  en vez de quedarse cargando para siempre. */
export function useAyudantes(): {
  ayudantes: Ayudante[];
  loading: boolean;
  error: string | null;
  retry: () => void;
} {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    subs.add(fn);
    if (cache === null && cacheError === null) load();
    return () => {
      subs.delete(fn);
    };
  }, []);
  return {
    ayudantes: cache ?? [],
    loading: cache === null && cacheError === null,
    error: cache === null ? cacheError : null,
    retry: () => {
      load();
    },
  };
}

export function useAyudante(id: string): {
  ayudante: Ayudante | undefined;
  loading: boolean;
  error: string | null;
  retry: () => void;
} {
  const { ayudantes, loading, error, retry } = useAyudantes();
  return { ayudante: ayudantes.find((a) => a.id === id), loading, error, retry };
}

// --- Mutaciones (API + cache local) ----------------------------------------

export async function createAyudante(
  name: string,
  appearance: AyudanteAppearance,
  aiuditas: string[] = [],
): Promise<Ayudante> {
  const a = await api.createAyudante({ name, appearance, aiuditas });
  cache = [...(cache ?? []), a];
  notify();
  return a;
}

export async function updateAyudante(
  id: string,
  patch: { name?: string; appearance?: AyudanteAppearance; instructions?: string },
): Promise<void> {
  replace(await api.updateAyudante(id, patch));
}

export async function deleteAyudante(id: string): Promise<void> {
  await api.deleteAyudante(id);
  cache = (cache ?? []).filter((x) => x.id !== id);
  notify();
}

/** Re-lee un ayudante del backend. Acciones y nivel se derivan allá en cada
 *  lectura: tras una corrida, el cache local queda viejo. */
export async function refreshAyudante(id: string): Promise<void> {
  replace(await api.ayudante(id));
}

/** Activa/actualiza una aiudita con su config (el backend la valida y acota). */
export async function setAiudita(
  id: string,
  aiuditaId: string,
  config: AiuditaConfig,
): Promise<void> {
  replace(await api.setAiudita(id, aiuditaId, config));
}

export async function removeAiudita(id: string, aiuditaId: string): Promise<void> {
  replace(await api.removeAiudita(id, aiuditaId));
}

// --- Catálogo de aiuditas (una sola fuente: el backend) ---------------------

let catCache: AiuditasCatalog | null = null;
let catError: string | null = null;
let catInflight: Promise<AiuditasCatalog | null> | null = null;
const catSubs = new Set<() => void>();

function loadCatalog(): void {
  if (catInflight) return;
  if (catError !== null) {
    catError = null;
    for (const f of catSubs) f();
  }
  catInflight = api
    .aiuditasCatalog()
    .then((c) => {
      catCache = c;
      for (const f of catSubs) f();
      return c;
    })
    .catch((e: Error) => {
      catError = e.message || "No se pudo cargar el catálogo.";
      for (const f of catSubs) f();
      return null;
    })
    .finally(() => {
      catInflight = null;
    });
}

/** Catálogo de aiuditas + error/reintento (mismo trato que useAyudantes). */
export function useCatalog(): {
  catalog: AiuditasCatalog | null;
  error: string | null;
  retry: () => void;
} {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    catSubs.add(fn);
    if (catCache === null && catError === null) loadCatalog();
    return () => {
      catSubs.delete(fn);
    };
  }, []);
  return { catalog: catCache, error: catError, retry: loadCatalog };
}
