"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, type SourceCap } from "@/lib/api";
import { agentDisplayName } from "@/lib/asistentes";
import { Drawer } from "@/components/drawer";
import { toast } from "@/components/toast";
import { INTEGRATION_HELP } from "@/lib/integration-help";
import { fieldsFor, EMAIL_PRESETS } from "@/lib/integration-fields";
import { ConnectionTester } from "@/components/connection-tester";

// El drawer solo necesita estos campos: así sirve tanto para el catálogo de
// Integraciones como para un sistema del mapa de un agente.
export type ConfigNode = {
  key: string;
  name: string;
  rol: string;
  logo: string | null;
  color: string;
  connected: boolean;
  // Semáforo del último "Probar conexión", igual que la lista de integraciones:
  // ok = pasó, error = falló (pinta "Revisar"), untested = configurado sin probar,
  // null = ni configurado. Sin él, el drawer no distingue una conexión rota.
  verified?: "ok" | "error" | "untested" | null;
  last_error?: string | null;
  live?: boolean;
  does?: string;
};

function WhatsAppPairing({ onChange }: { onChange: () => void }) {
  const [qr, setQr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [paired, setPaired] = useState<boolean | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Estado real de wacli (no la heurística del grafo).
    api
      .whatsappStatus()
      .then((s) => setPaired(s.connected))
      .catch(() => setPaired(false));
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function startQr() {
    setLoading(true);
    try {
      const res = await api.whatsappQr();
      if (res.connected) {
        setPaired(true);
        onChange();
        return;
      }
      setQr(res.qr);
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.whatsappStatus();
          if (s.connected) {
            if (pollRef.current) clearInterval(pollRef.current);
            setPaired(true);
            setQr(null);
            toast("WhatsApp conectado.", "success");
            onChange();
          }
        } catch {
          /* sigue intentando */
        }
      }, 3000);
    } catch (e) {
      toast(`No se pudo iniciar el emparejamiento: ${(e as Error).message}`, "error");
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    await api.whatsappLogout().catch(() => {});
    setPaired(false);
    setQr(null);
    onChange();
    toast("WhatsApp desconectado.", "info");
  }

  if (paired === null) {
    return <div className="skeleton h-40 w-full rounded-lg" />;
  }

  if (paired) {
    return (
      <div className="rounded-lg border border-ok/30 bg-ok-soft/40 px-4 py-4">
        <p className="text-cuerpo font-medium text-ok">WhatsApp conectado</p>
        <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">
          Tu número está vinculado. Tus clientes te escriben y tu equipo responde desde la consola.
        </p>
        <button
          onClick={logout}
          className="mt-3 rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-danger hover:text-danger"
        >
          Desvincular
        </button>
      </div>
    );
  }

  return (
    <div>
      {qr ? (
        <div className="flex flex-col items-center rounded-lg border border-line bg-surface px-4 py-5 text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={qr} alt="Código QR de WhatsApp" className="h-44 w-44" />
          <p className="mt-3 text-cuerpo font-medium text-ink">Escanea para vincular</p>
          <ol className="mx-auto mt-2 max-w-xs space-y-0.5 text-left text-apoyo leading-relaxed text-ink-3">
            <li>1. Abre WhatsApp en tu teléfono</li>
            <li>2. Ajustes &gt; Dispositivos vinculados &gt; Vincular un dispositivo</li>
            <li>3. Apunta la cámara a este código</li>
          </ol>
          <p className="mt-3 flex items-center gap-1.5 text-apoyo text-ink-3">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
            Esperando a que escanees…
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-line bg-surface px-4 py-5 text-center">
          <p className="text-cuerpo leading-relaxed text-ink-2">
            Vincula tu número de WhatsApp escaneando un código QR, como WhatsApp Web. Tu número, tu
            sesión; aiuda actúa encima.
          </p>
          <button
            onClick={startQr}
            disabled={loading}
            className="mt-3 rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
          >
            {loading ? "Generando QR…" : "Mostrar código QR"}
          </button>
        </div>
      )}
    </div>
  );
}

export function IntegrationConfigDrawer({
  node,
  onClose,
  onSaved,
}: {
  node: ConfigNode | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [caps, setCaps] = useState<SourceCap[]>([]);

  useEffect(() => {
    if (!node) return;
    // Guarda estilo useApi: si el usuario cambia de fuente antes de que llegue la
    // respuesta, `cancelado` (que el cleanup activa antes de re-disparar el efecto)
    // impide que la config de la fuente vieja pise las credenciales de la nueva.
    let cancelado = false;
    setValues({});
    setCaps([]);
    setLoading(true);
    api
      .integrationConfig(node.key)
      .then((c) => {
        if (cancelado) return;
        // El correo arranca en IMAP genérico salvo que ya se haya guardado otro proveedor.
        const base: Record<string, string> = node.key === "email" ? { provider: "imap" } : {};
        setValues({ ...base, ...(c.values ?? {}) });
        setConfigured(c.configured);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelado) setLoading(false);
      });
    api
      .integrationDetail(node.key)
      .then((d) => {
        if (cancelado) return;
        setCaps(d.capabilities ?? []);
      })
      .catch(() => {});
    return () => {
      cancelado = true;
    };
  }, [node]);

  async function toggleCap(cap: string) {
    if (!node) return;
    const target = caps.find((c) => c.cap === cap);
    if (!target || !target.toggleable) return;
    const prev = caps;
    const next = caps.map((c) => (c.cap === cap ? { ...c, enabled: !c.enabled } : c));
    setCaps(next);
    const disabled = next.filter((c) => c.toggleable && !c.enabled).map((c) => c.cap);
    try {
      await api.setIntegrationCapabilities(node.key, disabled);
    } catch {
      setCaps(prev);
      toast("No se pudo guardar el cambio.", "error");
    }
  }

  if (!node) {
    return (
      <Drawer open={false} onClose={onClose} title="">
        {null}
      </Drawer>
    );
  }

  const isExcel = node.key === "excel";
  const fields = fieldsFor(node.key);

  function setField(key: string, val: string) {
    setValues((v) => {
      const next = { ...v, [key]: val };
      // Correo: elegir Gmail/Outlook rellena los servidores que estén vacíos.
      if (node?.key === "email" && key === "provider") {
        for (const [pk, pv] of Object.entries(EMAIL_PRESETS[val] ?? {})) {
          if (!next[pk]) next[pk] = pv;
        }
      }
      return next;
    });
  }

  async function save() {
    if (!node) return;
    setSaving(true);
    try {
      await api.saveIntegration(node.key, values);
      // Honesto: guardar credenciales no es haber conectado. La conexión se afirma
      // cuando "Probar conexión" pasa (semáforo verified), no antes.
      toast("Credenciales guardadas. Prueba la conexión.", "success");
      onSaved();
      onClose();
    } catch (e) {
      toast(`No se pudo guardar: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  async function disconnect() {
    if (!node) return;
    try {
      await api.disconnectIntegration(node.key);
      toast(`${node.name} desconectado.`, "info");
      onSaved();
      onClose();
    } catch (e) {
      toast(`No se pudo desconectar: ${(e as Error).message}`, "error");
    }
  }

  return (
    <Drawer open={!!node} onClose={onClose} title={node.name} subtitle={node.rol}>
      <div className="space-y-5">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-line bg-surface">
            {node.logo ? (
              <img src={node.logo} alt="" className="h-6 w-6 object-contain" />
            ) : (
              <span className="text-seccion font-bold" style={{ color: node.color }}>
                {node.name.slice(0, 2)}
              </span>
            )}
          </span>
          {node.verified === "error" ? (
            <span
              title={node.last_error ?? undefined}
              className="flex items-center gap-1.5 rounded-full bg-danger-soft px-2.5 py-1 text-sello font-medium text-danger"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-danger" />
              Revisar
            </span>
          ) : node.connected ? (
            <span className="flex items-center gap-1.5 rounded-full bg-ok-soft px-2.5 py-1 text-sello font-medium text-ok">
              <span className="h-1.5 w-1.5 rounded-full bg-ok" />
              {node.verified === "ok" ? "Verificado" : "Conectado"}
            </span>
          ) : (
            <span className="rounded-full bg-panel px-2.5 py-1 text-sello font-medium text-ink-2">
              Sin conectar
            </span>
          )}
          <Link
            href={`/integraciones/detalle?key=${node.key}`}
            onClick={onClose}
            className="ml-auto text-cuerpo font-medium text-accent-ink transition-colors hover:underline"
          >
            Abrir vista completa
          </Link>
        </div>

        {node.does && (
          <div className="rounded-lg border border-line bg-panel/40 px-3.5 py-3">
            <p className="text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
              ¿Cómo <span className="italic">aiuda</span>?
            </p>
            <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">{node.does}</p>
            {node.live === false && (
              <p className="mt-2 text-apoyo leading-relaxed text-ink-3">
                Guarda tus credenciales para dejarla conectada. La sincronización automática
                por negocio se habilita contigo en el alta del piloto.
              </p>
            )}
          </div>
        )}

        {!isExcel && node.key !== "whatsapp" && caps.length > 0 && (
          <div className="rounded-lg border border-line bg-surface px-3.5 py-3">
            <p className="text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
              Qué obtener de {node.name}
            </p>
            <p className="mt-1 text-apoyo leading-relaxed text-ink-3">
              Elige qué le da esta fuente a tu equipo. Empieza a obtenerse cuando la conectes.
            </p>
            <ul className="mt-2.5 space-y-2.5">
              {caps.map((c) => (
                <li key={c.cap} className="flex items-start gap-2.5">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={c.enabled}
                    aria-label={c.label}
                    disabled={!c.toggleable}
                    onClick={() => toggleCap(c.cap)}
                    className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded transition-colors ${
                      c.enabled
                        ? "bg-accent text-surface"
                        : c.toggleable
                          ? "border border-line-strong"
                          : "border border-dashed border-line"
                    } ${c.toggleable ? "cursor-pointer" : "cursor-default"}`}
                  >
                    {c.enabled && (
                      <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none">
                        <path
                          d="m2.5 6 2.5 2.5 4.5-5"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    )}
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="text-cuerpo font-medium text-ink">
                      {c.label}
                      {!c.live && <span className="font-normal text-ink-3"> · por conectar</span>}
                    </p>
                    {c.agents.length > 0 && (
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        <span className="text-apoyo text-ink-3">→</span>
                        {c.agents.map((ag) => (
                          <span
                            key={ag.slug}
                            className="flex items-center gap-1 rounded-full bg-panel px-1.5 py-0.5 text-sello text-ink-2"
                          >
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={ag.avatar} alt="" className="h-3.5 w-3.5 rounded-full object-cover" />
                            {agentDisplayName(ag.slug)}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {node.key === "whatsapp" ? (
          <WhatsAppPairing onChange={onSaved} />
        ) : isExcel ? (
          <div className="rounded-lg border border-line bg-panel/40 px-4 py-4 text-cuerpo leading-relaxed text-ink-2">
            Excel y CSV no necesitan credenciales. Sube cualquier hoja —clientes, productos,
            facturas, citas o prospectos— y la IA detecta qué es y la carga sola.
            <div className="mt-3">
              <Link
                href="/importar"
                className="inline-block rounded-md bg-accent px-3 py-1.5 text-cuerpo font-medium text-surface hover:bg-accent-strong"
              >
                Ir a Importar
              </Link>
            </div>
          </div>
        ) : loading ? (
          <div className="skeleton h-40 w-full rounded-lg" />
        ) : (
          <>
            <div className="space-y-3">
              {fields.map((f) => (
                <div key={f.key}>
                  <label className="text-cuerpo font-medium text-ink">{f.label}</label>
                  {f.type === "select" ? (
                    <select
                      value={values[f.key] ?? f.options?.[0]?.value ?? ""}
                      onChange={(e) => setField(f.key, e.target.value)}
                      className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-rotulo text-ink focus:border-accent focus:outline-none"
                    >
                      {f.options?.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={f.secret ? "password" : "text"}
                      value={values[f.key] ?? ""}
                      placeholder={f.placeholder}
                      onChange={(e) => setField(f.key, e.target.value)}
                      className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-rotulo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
                    />
                  )}
                  {f.hint && <p className="mt-1 text-apoyo leading-relaxed text-ink-3">{f.hint}</p>}
                </div>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={save}
                disabled={saving}
                className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
              >
                {saving ? "Guardando…" : configured ? "Guardar cambios" : "Conectar"}
              </button>
              <ConnectionTester intKey={node.key} disabled={!configured} />
              {configured && (
                <button
                  onClick={disconnect}
                  className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-danger hover:text-danger"
                >
                  Desconectar
                </button>
              )}
            </div>

            {node.key === "whatsapp_cloud" && configured && (
              <div className="rounded-lg border border-line bg-panel/40 px-3.5 py-3">
                <p className="text-cuerpo leading-relaxed text-ink-2">
                  Con las credenciales guardadas, activa esta vía oficial como TU canal de
                  WhatsApp: recordatorios y respuestas saldrán por aquí (y no por wacli).
                </p>
                <button
                  onClick={async () => {
                    try {
                      await api.activateWhatsappCloud();
                      toast("WhatsApp Business (oficial) es ahora tu canal.", "success");
                      onSaved();
                    } catch (e) {
                      toast(`No se pudo activar: ${(e as Error).message}`, "error");
                    }
                  }}
                  className="mt-2 rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink transition-colors hover:border-accent hover:text-accent-ink"
                >
                  Usar como mi canal de WhatsApp
                </button>
              </div>
            )}

            <p className="border-t border-line/60 pt-3 text-apoyo leading-relaxed text-ink-3">
              Tus credenciales se guardan cifradas en esta instalación y solo se usan para
              conectar este sistema.
            </p>
          </>
        )}

        <IntegrationHelp nodeKey={node.key} name={node.name} />
      </div>
    </Drawer>
  );
}

function IntegrationHelp({ nodeKey, name }: { nodeKey: string; name: string }) {
  const help = INTEGRATION_HELP[nodeKey];
  const [open, setOpen] = useState(false);
  if (!help) return null;
  return (
    <div className="border-t border-line/60 pt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-cuerpo font-medium text-ink transition-colors hover:text-accent-ink"
      >
        Cómo conectar {name}
        <svg viewBox="0 0 12 12" className={`h-3 w-3 text-ink-3 transition-transform ${open ? "rotate-90" : ""}`} fill="none">
          <path d="m4.5 3 3 3-3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="mt-2.5 space-y-3">
          <p className="text-cuerpo leading-relaxed text-ink-2">{help.intro}</p>
          {help.steps.length > 0 && (
            <ol className="space-y-1.5">
              {help.steps.map((s, i) => (
                <li key={i} className="flex gap-2 text-cuerpo leading-relaxed text-ink-2">
                  <span className="tnum shrink-0 font-medium text-ink-3">{i + 1}.</span>
                  {s}
                </li>
              ))}
            </ol>
          )}
          {help.credentials.length > 0 && (
            <div className="rounded-md border border-line bg-panel/40 p-3">
              <p className="text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">Dónde obtener cada dato</p>
              <ul className="mt-1.5 space-y-1.5">
                {help.credentials.map((c) => (
                  <li key={c.field} className="text-apoyo leading-relaxed text-ink-2">
                    <span className="font-medium text-ink">{c.field}:</span> {c.where}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
