"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  api,
  type IntegrationConfig,
  type IntegrationDetail,
  type SourceCap,
} from "@/lib/api";
import { ErrorState, Skeleton } from "@/components/ui";
import { usePageTrail } from "@/components/rastro";
import { toast } from "@/components/toast";
import { fieldsFor, EMAIL_PRESETS } from "@/lib/integration-fields";
import { agentDisplayName } from "@/lib/asistentes";
import { ConnectionTester } from "@/components/connection-tester";

export default function IntegrationPage() {
  // useSearchParams exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={null}>
      <IntegrationDetail />
    </Suspense>
  );
}

function IntegrationDetail() {
  const key = useSearchParams().get("key") ?? "";
  const [detail, setDetail] = useState<IntegrationDetail | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.integrationDetail(key), api.integrationConfig(key)])
      .then(([d, c]: [IntegrationDetail, IntegrationConfig]) => {
        setDetail(d);
        const base: Record<string, string> = d.key === "email" ? { provider: "imap" } : {};
        setValues({ ...base, ...(c.values ?? {}) });
        setConfigured(c.configured);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [key]);

  useEffect(load, [load]);
  usePageTrail(detail?.name ?? "Integración");

  async function toggleCap(cap: SourceCap) {
    if (!detail || !cap.toggleable) return;
    const next = detail.capabilities.map((c) =>
      c.cap === cap.cap ? { ...c, enabled: !c.enabled } : c,
    );
    setDetail({ ...detail, capabilities: next });
    const disabled = next.filter((c) => c.toggleable && !c.enabled).map((c) => c.cap);
    try {
      await api.setIntegrationCapabilities(key, disabled);
    } catch {
      load();
      toast("No se pudo guardar el cambio.", "error");
    }
  }

  async function save() {
    if (!detail) return;
    setSaving(true);
    try {
      await api.saveIntegration(key, values);
      toast(`${detail.name} conectado.`, "success");
      load();
    } catch (e) {
      toast(`No se pudo guardar: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  async function disconnect() {
    if (!detail) return;
    try {
      await api.disconnectIntegration(key);
      toast(`${detail.name} desconectado.`, "info");
      load();
    } catch (e) {
      toast(`No se pudo desconectar: ${(e as Error).message}`, "error");
    }
  }

  if (error) return <ErrorState message={error} retry={load} />;

  const fields = detail ? fieldsFor(detail.key) : [];
  const inputCls =
    "w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none";

  function setField(fk: string, val: string) {
    setValues((v) => {
      const next = { ...v, [fk]: val };
      if (detail?.key === "email" && fk === "provider") {
        for (const [pk, pv] of Object.entries(EMAIL_PRESETS[val] ?? {})) {
          if (!next[pk]) next[pk] = pv;
        }
      }
      return next;
    });
  }

  return (
    <div className="max-w-2xl">
      {loading && !detail ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : detail ? (
        <div className="space-y-5">
          {/* Hero */}
          <header className="flex items-center gap-3.5 rounded-xl border border-line bg-surface px-4 py-3.5">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-line bg-panel/40">
              {detail.logo ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={detail.logo} alt="" className="h-7 w-7 object-contain" />
              ) : (
                <span className="text-cuerpo font-bold" style={{ color: detail.color }}>
                  {detail.name.slice(0, 2)}
                </span>
              )}
            </span>
            <div className="min-w-0 flex-1">
              <h1 className="text-seccion font-semibold tracking-tight text-ink">{detail.name}</h1>
              <p className="text-cuerpo text-ink-3">{detail.rol}</p>
            </div>
            <span
              className={`shrink-0 rounded-full px-2.5 py-1 text-sello font-medium ${
                detail.connected ? "bg-ok-soft text-ok" : "bg-panel text-ink-2"
              }`}
            >
              {detail.connected ? "Conectado" : detail.live ? "Sin conectar" : "Por conectar"}
            </span>
          </header>

          {/* Aviso honesto: vía no oficial (ej. WhatsApp por wacli/Evolution),
              mismo patrón que el modo de suscripción del proveedor de IA. */}
          {detail.warning && (
            <div className="flex items-start gap-2.5 rounded-lg border border-warn/40 bg-warn-soft px-3.5 py-3">
              <svg viewBox="0 0 14 14" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" fill="none">
                <path
                  d="M7 1.6 13 12H1L7 1.6ZM7 5.4v3M7 10.1h.01"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <div className="text-cuerpo leading-relaxed text-ink-2">
                <span className="font-semibold text-warn">Antes de conectar.</span>{" "}
                {detail.warning}
              </div>
            </div>
          )}

          {/* ¿Cómo aiuda? */}
          {detail.does && (
            <section className="rounded-lg border border-line bg-panel/40 px-4 py-3">
              <p className="text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
                ¿Cómo <span className="italic normal-case">aiuda</span>?
              </p>
              <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">{detail.does}</p>
            </section>
          )}

          {/* Qué obtener: capacidades como tarjetas con su aiudante y toggle */}
          {detail.capabilities.length > 0 && (
            <section>
              <h2 className="text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
                Qué obtener de {detail.name}
              </h2>
              <p className="mt-1 text-apoyo text-ink-3">
                Elige qué le da esta fuente a tu equipo. Empieza a obtenerse cuando la conectes.
              </p>
              <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {detail.capabilities.map((c) => (
                  <div
                    key={c.cap}
                    className={`rounded-lg border px-3.5 py-3 ${
                      c.enabled && c.live ? "border-line bg-surface" : "border-line/60 bg-panel/30"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-cuerpo font-medium text-ink">{c.label}</p>
                      {c.toggleable ? (
                        <button
                          onClick={() => toggleCap(c)}
                          role="switch"
                          aria-checked={c.enabled}
                          aria-label={`${c.enabled ? "Apagar" : "Prender"} ${c.label}`}
                          className={`relative h-4 w-7 shrink-0 rounded-full transition-colors ${
                            c.enabled ? "bg-accent" : "bg-line-strong"
                          }`}
                        >
                          <span
                            className={`absolute top-0.5 h-3 w-3 rounded-full bg-surface transition-transform ${
                              c.enabled ? "translate-x-3.5" : "translate-x-0.5"
                            }`}
                          />
                        </button>
                      ) : (
                        <span className="shrink-0 rounded bg-panel px-1.5 py-px text-rotulo font-medium uppercase tracking-[0.04em] text-ink-3">
                          Por conectar
                        </span>
                      )}
                    </div>
                    {c.desc && <p className="mt-1 text-apoyo leading-relaxed text-ink-3">{c.desc}</p>}
                    {c.agents.length > 0 && (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        {c.agents.map((a) => (
                          <Link
                            key={a.slug}
                            href="/ayudantes"
                            className="flex items-center gap-1.5 rounded-full bg-panel px-1.5 py-0.5 text-sello text-ink-2 transition-colors hover:text-ink"
                          >
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={a.avatar} alt="" className="h-3.5 w-3.5 rounded-full" />
                            {agentDisplayName(a.slug)}
                          </Link>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Credenciales + Probar conexión. Solo si la fuente declara campos: excel se
              sube como archivo, whatsapp se empareja por QR y sat vive en su propia
              pantalla. Antes esto era un `!== "excel"` clavado a mano y las otras dos
              acababan pidiendo un secreto inventado. */}
          {fields.length > 0 && (
            <section className="rounded-lg border border-line bg-surface px-4 py-3.5">
              <h2 className="text-cuerpo font-semibold text-ink">Credenciales</h2>
              <p className="mt-0.5 text-apoyo text-ink-3">
                Viven cifradas en tu negocio y solo se usan para conectar este sistema.
              </p>
              <div className="mt-3 space-y-3">
                {fields.map((f) => (
                  <div key={f.key}>
                    <label className="text-rotulo uppercase tracking-[0.06em] text-ink-3">{f.label}</label>
                    {f.type === "select" ? (
                      <select
                        className={`mt-1 ${inputCls}`}
                        value={values[f.key] ?? f.options?.[0]?.value ?? ""}
                        onChange={(e) => setField(f.key, e.target.value)}
                      >
                        {f.options?.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className={`mt-1 ${inputCls}`}
                        type={f.secret ? "password" : "text"}
                        placeholder={f.placeholder}
                        value={values[f.key] ?? ""}
                        onChange={(e) => setField(f.key, e.target.value)}
                      />
                    )}
                    {f.hint && <p className="mt-1 text-apoyo leading-relaxed text-ink-3">{f.hint}</p>}
                  </div>
                ))}
              </div>
              <div className="mt-3.5 flex flex-wrap items-center gap-2">
                <button
                  onClick={save}
                  disabled={saving}
                  className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                >
                  {saving ? "Guardando…" : configured ? "Guardar cambios" : "Conectar"}
                </button>
                <ConnectionTester intKey={detail.key} disabled={!configured} />
                {configured && (
                  <button
                    onClick={disconnect}
                    className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-danger hover:text-danger"
                  >
                    Desconectar
                  </button>
                )}
              </div>
            </section>
          )}
        </div>
      ) : null}
    </div>
  );
}
