"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, type SourceCap, type WhatsappStatus } from "@/lib/api";
import { Drawer } from "@/components/drawer";
import {
  SIN_ESTRENAR_NOTA,
  SinEstrenar,
  inputCls,
  Estado,
  PrimaryButton,
  QuietButton,
} from "@/components/ui";
import { toast } from "@/components/toast";
import { INTEGRATION_HELP } from "@/lib/integration-help";
import { fieldsFor, EMAIL_PRESETS } from "@/lib/integration-fields";
import { ConnectionTester } from "@/components/connection-tester";

// El panel solo necesita estos campos: así sirve tanto para la lista de Conexiones
// como para un sistema visto desde la ficha de un ayudante.
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
  estrenada?: boolean;
  does?: string;
  // Aviso honesto de una vía no oficial: se muestra una vez, al conectar.
  warning?: string | null;
};

// Lo que se le dice al dueño cuando su número ya está vinculado, según cómo
// está la sesión AHORA (no como quedó guardada).
const WA_VINCULADO: Record<string, { titulo: string; texto: string; ok: boolean }> = {
  conectado: {
    titulo: "WhatsApp conectado",
    texto: "Tus clientes te escriben y tu equipo responde desde la consola.",
    ok: true,
  },
  conectando: {
    titulo: "Conectando con WhatsApp…",
    texto: "Tu número está vinculado. En unos segundos queda listo.",
    ok: true,
  },
  sin_conexion: {
    titulo: "Sin conexión con WhatsApp",
    texto:
      "Tu número sigue vinculado, pero ahora no hay conexión. aiuda reintenta solo; revisa el internet de esta computadora.",
    ok: false,
  },
  externo: {
    titulo: "WhatsApp abierto en otro programa",
    texto:
      "Tu número está vinculado, pero otro programa de esta computadora tiene abierta la sesión. aiuda la retoma sola en cuanto ese programa se cierre.",
    ok: false,
  },
};

/** Instalar el conector, vincular el número con un código y ver cómo está la sesión.
 *  Es LA forma de conectar WhatsApp: vive en el panel de Conexiones y en el cierre
 *  del asistente de primer arranque. `discreto` pinta su acción sin relleno, para
 *  cuando la pantalla que lo aloja ya tiene su propio botón principal. */
export function WhatsAppPairing({
  onChange,
  aviso,
  discreto = false,
}: {
  onChange: () => void;
  aviso?: string | null;
  discreto?: boolean;
}) {
  const boton = discreto ? "btn btn-secondary" : "btn btn-primary";
  const [st, setSt] = useState<WhatsappStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [instalando, setInstalando] = useState(false);
  // ¿Este drawer pidió un QR que sigue sin escanearse? Si se cierra así, se cancela.
  const esperandoQr = useRef(false);

  useEffect(() => {
    let vivo = true;
    // Estado EN VIVO de wacli, cada 3 s: así el QR se refresca cuando rota y la
    // etiqueta sigue a la sesión (conectando, conectado, sin conexión).
    const leer = () =>
      api
        .whatsappStatus()
        .then((s) => {
          if (!vivo) return;
          if (esperandoQr.current && s.connected) {
            esperandoQr.current = false;
            toast("WhatsApp conectado.", "success");
            onChange();
          }
          setSt(s);
        })
        .catch(() => {
          /* sigue intentando */
        });
    leer();
    const id = setInterval(leer, 3000);
    return () => {
      vivo = false;
      clearInterval(id);
      // Cerrar sin escanear no deja el emparejamiento ocupando el WhatsApp.
      if (esperandoQr.current) api.whatsappQrCancelar().catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startQr() {
    setLoading(true);
    try {
      const res = await api.whatsappQr();
      esperandoQr.current = !res.connected;
      setSt(await api.whatsappStatus());
      if (res.connected) onChange();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setLoading(false);
    }
  }

  async function cancelarQr() {
    esperandoQr.current = false;
    await api.whatsappQrCancelar().catch(() => {});
    setSt(await api.whatsappStatus());
  }

  async function instalar() {
    setInstalando(true);
    try {
      await api.whatsappInstalar();
      setSt(await api.whatsappStatus());
      toast("Conector de WhatsApp instalado.", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setInstalando(false);
    }
  }

  async function logout() {
    try {
      await api.whatsappLogout();
      toast("WhatsApp desvinculado.", "info");
    } catch (e) {
      toast((e as Error).message, "error");
    }
    setSt(await api.whatsappStatus());
    onChange();
  }

  if (st === null) {
    return <div className="skeleton h-40 w-full rounded-lg" />;
  }

  if (st.connected) {
    const v = WA_VINCULADO[st.estado] ?? WA_VINCULADO.conectando;
    return (
      <div className={`rounded-2xl px-5 py-4 ${v.ok ? "bg-panel" : "bg-panel"}`}>
        <p
          className="mark !text-cuerpo !font-semibold !text-ink"
          style={
            { "--mark": v.ok ? "var(--color-ok)" : "var(--color-warn)" } as React.CSSProperties
          }
        >
          {v.titulo}
        </p>
        <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">
          {st.telefono ? `Número vinculado: +${st.telefono}. ` : ""}
          {v.texto}
        </p>
        <div className="mt-4 flex flex-wrap items-start gap-2">
          <ConnectionTester intKey="whatsapp" />
          <QuietButton onClick={logout}>
            Desvincular
          </QuietButton>
        </div>
      </div>
    );
  }

  if (!st.instalado || st.estado === "desactualizado") {
    const actualizar = st.instalado;
    // Honesto: si ya está la versión que este aiuda sabe instalar, reinstalarla
    // no arregla nada. Hace falta un aiuda más nuevo.
    const sinNadaQueInstalar = actualizar && st.version === st.version_fijada;
    return (
      <div className="rounded-2xl bg-panel px-5 py-5">
        {st.no_se_puede || sinNadaQueInstalar ? (
          <p className="text-cuerpo leading-relaxed text-ink-2">
            {st.no_se_puede ??
              "WhatsApp pidió una versión del conector más nueva que la que trae este aiuda. Actualiza aiuda para volver a conectar."}
          </p>
        ) : (
          <>
            <p className="text-cuerpo leading-relaxed text-ink-2">
              {actualizar
                ? "WhatsApp pidió una versión más nueva del conector. Actualízalo para volver a conectar."
                : "Para conectar tu WhatsApp, esta computadora necesita un conector. Se instala solo, en menos de un minuto. Después escaneas un código con tu teléfono, como en WhatsApp Web."}
            </p>
            <button onClick={instalar} disabled={instalando} className={`${boton} mt-4`}>
              {instalando
                ? "Instalando…"
                : actualizar
                  ? "Actualizar el conector"
                  : "Instalar el conector"}
            </button>
            <p className="mt-4 text-apoyo leading-relaxed text-ink-3">
              El conector se llama wacli (github.com/openclaw/wacli). Es software libre de
              terceros, con licencia MIT y componentes GPL-3.0. Se descarga de su página oficial y
              se verifica antes de guardarse.
            </p>
          </>
        )}
      </div>
    );
  }

  return (
    <div>
      {st.qr ? (
        <div className="flex flex-col items-center rounded-2xl bg-panel px-5 py-5 text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={st.qr}
            alt="Código QR de WhatsApp"
            className="h-44 w-44 rounded-lg bg-surface p-2"
          />
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
          <button
            onClick={cancelarQr}
            className="mt-2 text-apoyo text-ink-3 underline underline-offset-2 hover:text-ink"
          >
            Cancelar
          </button>
        </div>
      ) : (
        <div className="rounded-2xl bg-panel px-5 py-5">
          <p className="text-cuerpo leading-relaxed text-ink-2">
            {st.estado === "sesion_cerrada"
              ? "WhatsApp cerró la sesión de esta computadora, casi siempre porque se quitó desde el teléfono en Dispositivos vinculados. Vuelve a escanear el código QR."
              : "Vincula tu número de WhatsApp escaneando un código con tu teléfono, como en WhatsApp Web. Es tu número y tu sesión; aiuda trabaja encima."}
          </p>
          {st.aviso && st.estado !== "sesion_cerrada" && (
            <p className="mt-2 text-cuerpo leading-relaxed text-danger">{st.aviso}</p>
          )}
          {/* Lo que hay que saber antes de vincular. Solo aquí: ya conectado no se repite. */}
          {aviso && (
            <p className="mt-3 text-apoyo leading-relaxed text-ink-2">
              <span className="font-semibold text-ink">Antes de conectar.</span> {aviso}
            </p>
          )}
          <button onClick={startQr} disabled={loading} className={`${boton} mt-4`}>
            {loading ? "Preparando el código…" : "Conectar mi WhatsApp"}
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

  const llave = node?.key ?? "";
  useEffect(() => {
    if (!llave) return;
    // Por LLAVE y no por objeto: quien monta el panel le pasa el nodo fresco tras
    // cada recarga, y eso no debe vaciar lo que el dueño va escribiendo.
    // Guarda estilo useApi: si el usuario cambia de fuente antes de que llegue la
    // respuesta, `cancelado` (que el cleanup activa antes de re-disparar el efecto)
    // impide que la config de la fuente vieja pise las credenciales de la nueva.
    let cancelado = false;
    setValues({});
    setCaps([]);
    setLoading(true);
    api
      .integrationConfig(llave)
      .then((c) => {
        if (cancelado) return;
        // El correo arranca en IMAP genérico salvo que ya se haya guardado otro proveedor.
        const base: Record<string, string> = llave === "email" ? { provider: "imap" } : {};
        setValues({ ...base, ...(c.values ?? {}) });
        setConfigured(c.configured);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelado) setLoading(false);
      });
    api
      .integrationDetail(llave)
      .then((d) => {
        if (cancelado) return;
        setCaps(d.capabilities ?? []);
      })
      .catch(() => {});
    return () => {
      cancelado = true;
    };
  }, [llave]);

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
      // El panel se queda abierto: lo que sigue es probarla, y el botón está aquí.
      toast("Credenciales guardadas. Ahora prueba la conexión.", "success");
      setConfigured(true);
      onSaved();
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
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-fill">
            {node.logo ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img src={node.logo} alt="" className="h-5 w-5 object-contain" />
            ) : (
              <span className="text-rotulo font-semibold text-ink-2">{node.name.slice(0, 2)}</span>
            )}
          </span>
          {node.verified === "error" ? (
            <Estado tono="falla">
              Revisar
            </Estado>
          ) : node.connected ? (
            <Estado tono="ok">
              Conectado
            </Estado>
          ) : (
            <Estado>Sin conectar</Estado>
          )}
          {node.estrenada === false && <SinEstrenar />}
        </div>

        {node.verified === "error" && node.last_error && (
          <p className="text-cuerpo leading-relaxed text-ink-2">
            La última prueba falló: {node.last_error}
          </p>
        )}

        {node.does && (
          <div>
            <p className="text-cuerpo leading-relaxed text-ink-2">{node.does}</p>
            {node.estrenada === false && (
              <p className="mt-2 text-apoyo leading-relaxed text-ink-3">{SIN_ESTRENAR_NOTA}</p>
            )}
          </div>
        )}

        {!isExcel && node.key !== "whatsapp" && caps.length > 0 && (
          <div>
            <p className="text-cuerpo font-semibold text-ink">Qué quieres traer de {node.name}</p>
            <ul className="mt-2 divide-y divide-line border-y border-line">
              {caps.map((c) => (
                <li key={c.cap} className="flex items-start gap-3 py-3">
                  <span className="min-w-0 flex-1">
                    <span className="block text-cuerpo text-ink">{c.label}</span>
                    {c.agents.length > 0 && (
                      <span className="mt-0.5 block text-apoyo text-ink-3">
                        Lo usa {c.agents.map((a) => a.name).join(", ")}
                      </span>
                    )}
                  </span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={c.enabled}
                    aria-label={`${c.enabled ? "Dejar de traer" : "Traer"} ${c.label}`}
                    disabled={!c.toggleable}
                    onClick={() => toggleCap(c.cap)}
                    className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
                      c.enabled ? "bg-accent" : "bg-line-strong"
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 rounded-full bg-surface shadow transition-transform ${
                        c.enabled ? "translate-x-6" : "translate-x-1"
                      }`}
                    />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {node.key === "whatsapp" ? (
          <WhatsAppPairing onChange={onSaved} aviso={node.warning} />
        ) : isExcel ? (
          <div className="rounded-2xl bg-panel px-5 py-4 text-cuerpo leading-relaxed text-ink-2">
            No hay nada que conectar: subes tu hoja (clientes, productos, facturas, citas o
            prospectos) y tu IA reconoce qué es y la carga.
            <div className="mt-4">
              <Link href="/importar" onClick={onClose} className="btn btn-primary">
                Subir un archivo
              </Link>
            </div>
          </div>
        ) : loading ? (
          <div className="skeleton h-40 w-full rounded-lg" />
        ) : fields.length === 0 ? (
          // Una fuente que no declara campos no se conecta desde aquí (sat vive en su
          // propia pantalla). Antes caía al formulario genérico y pedía un secreto
          // inventado que se guardaba sin cifrar.
          <div className="rounded-2xl bg-panel px-5 py-4 text-cuerpo leading-relaxed text-ink-2">
            {node.key === "sat"
              ? "El SAT tiene su propia pantalla: ahí cargas tu e.firma, importas tus XML y ves tu bóveda."
              : "Esta conexión no se hace capturando datos aquí."}
            {node.key === "sat" && (
              <div className="mt-4">
                <Link href="/sat" onClick={onClose} className="btn btn-primary">
                  Abrir el SAT
                </Link>
              </div>
            )}
          </div>
        ) : (
          <>
            <div className="space-y-4">
              {fields.map((f) => (
                <div key={f.key}>
                  <label className="block text-cuerpo font-semibold text-ink">{f.label}</label>
                  {f.type === "select" ? (
                    <select
                      value={values[f.key] ?? f.options?.[0]?.value ?? ""}
                      onChange={(e) => setField(f.key, e.target.value)}
                      className={`${inputCls} mt-2`}
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
                      className={`${inputCls} mt-2`}
                    />
                  )}
                  {f.hint && <p className="mt-1.5 text-apoyo leading-relaxed text-ink-3">{f.hint}</p>}
                </div>
              ))}
            </div>

            <div className="flex flex-wrap items-start gap-2">
              <PrimaryButton onClick={save} disabled={saving}>
                {saving ? "Guardando…" : configured ? "Guardar cambios" : "Conectar"}
              </PrimaryButton>
              <ConnectionTester intKey={node.key} disabled={!configured} onProbada={onSaved} />
              {configured && (
                <button onClick={disconnect} className="btn btn-quiet ml-auto">
                  Desconectar
                </button>
              )}
            </div>

            {node.key === "whatsapp_cloud" && configured && (
              <div className="rounded-2xl bg-panel px-5 py-4">
                <p className="text-cuerpo leading-relaxed text-ink-2">
                  Con las credenciales guardadas, activa esta vía oficial como TU canal de
                  WhatsApp: recordatorios y respuestas saldrán por aquí, y no por tu número
                  vinculado.
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
                  className="btn btn-secondary mt-3"
                >
                  Usar como mi canal de WhatsApp
                </button>
              </div>
            )}

            <p className="text-apoyo leading-relaxed text-ink-3">
              Tus credenciales se guardan cifradas en esta computadora y solo se usan para
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
    <div className="border-t border-line pt-4">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between text-cuerpo font-medium text-ink hover:text-accent-ink"
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
            <div className="rounded-2xl bg-panel px-5 py-4">
              <p className="eyebrow">dónde obtener cada dato</p>
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
