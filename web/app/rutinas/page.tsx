"use client";

import { useEffect, useMemo, useState } from "react";
import {
  PageHeader,
  Skeleton,
  ErrorState,
  PrimaryButton,
  SecondaryButton,
  Tabs,
  useConfirm,
} from "@/components/ui";
import { Drawer } from "@/components/drawer";
import { AnimatedNumber, Collapse } from "@/components/motion";
import { toast } from "@/components/toast";
import { fechaHora, haceTiempo } from "@/lib/format";
import {
  api,
  type CuaCapacidad,
  type CuaEstado,
  type CuaMision,
  type CuaSesionHandoff,
  type RutinaBackoffice,
} from "@/lib/api";

// Estado real de una misión, con el color del punto en la línea de tiempo y si "late"
// (queued/running siguen vivos: pulso y refresco). Labels honestos: nada de horarios.
const ESTADO: Record<
  CuaMision["status"],
  { label: string; cls: string; dot: string; vivo: boolean }
> = {
  queued: { label: "En cola", cls: "bg-line/60 text-ink-3", dot: "bg-ink-3/60", vivo: true },
  running: {
    label: "Adentro del portal",
    cls: "bg-accent-soft text-accent-ink",
    dot: "bg-accent",
    vivo: true,
  },
  done: { label: "Trajo el resultado", cls: "bg-ok/15 text-ok", dot: "bg-ok", vivo: false },
  failed: { label: "No pudo", cls: "bg-danger-soft text-danger", dot: "bg-danger", vivo: false },
};

const instruccionDe = (m: CuaMision): string | null =>
  typeof m.data?._instruccion === "string" && m.data._instruccion ? m.data._instruccion : null;

// Marca de tiempo "protagonista" de una misión: la más avanzada que tenga.
const cuando = (m: CuaMision): string | null => m.finishedAt || m.startedAt || m.createdAt;

// Ícono "correr" (triángulo de reproducción): la acción de despachar un encargo.
function PlayIcon({ className = "h-3 w-3" }: { className?: string }) {
  return (
    <svg viewBox="0 0 12 12" className={className} fill="currentColor" aria-hidden="true">
      <path d="M3.5 2.6v6.8a.5.5 0 0 0 .77.42l5.2-3.4a.5.5 0 0 0 0-.84l-5.2-3.4a.5.5 0 0 0-.77.42Z" />
    </svg>
  );
}

// Ícono "portal / entrada": el asistente entra a un sitio por su cuenta.
function PortalIcon({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 14 14" className={className} fill="none" aria-hidden="true">
      <rect x="2" y="2.5" width="10" height="9" rx="1.4" stroke="currentColor" strokeWidth="1.2" />
      <path d="M2 5h10" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <circle cx="3.7" cy="3.75" r="0.5" fill="currentColor" />
    </svg>
  );
}

export default function RutinasPage() {
  const [misiones, setMisiones] = useState<CuaMision[] | null>(null);
  const [rutinas, setRutinas] = useState<RutinaBackoffice[] | null>(null);
  const [caps, setCaps] = useState<CuaCapacidad[]>([]);
  const [estado, setEstado] = useState<CuaEstado | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Compositor "manda un encargo".
  const [capSel, setCapSel] = useState<string | null>(null);
  const [instruccion, setInstruccion] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [guardarAbierto, setGuardarAbierto] = useState(false);
  const [nombreRutina, setNombreRutina] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [corriendoId, setCorriendoId] = useState<string | null>(null);

  // Portales vive en un Drawer (fuera del flujo vertical); la vista de "lo que ya
  // existe" (recetas / bitácora) va tras un tab en vez de apilarse.
  const [portalesAbierto, setPortalesAbierto] = useState(false);
  const [tab, setTab] = useState<"rutinas" | "actividad">("rutinas");

  const { confirm, dialog } = useConfirm();

  const cargar = async () => {
    try {
      const [m, c, r] = await Promise.all([
        api.cuaMisiones(),
        api.cuaCapacidades(),
        api.cuaRutinas(),
      ]);
      setMisiones(m);
      setCaps(c);
      setRutinas(r);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    // El estado del servidor (navegador + credencial) es un aviso, no un bloqueo: si
    // falla su consulta, la página sigue; el backend corta honesto de todas formas.
    api.cuaEstado().then(setEstado).catch(() => {});
  };

  useEffect(() => {
    cargar();
  }, []);

  // Mientras haya un encargo en cola o corriendo, refresca la bitácora sola (headless,
  // en segundo plano). No re-pide capacidades ni rutinas: no cambian por su cuenta.
  const activos = (misiones ?? []).some((m) => m.status === "queued" || m.status === "running");
  useEffect(() => {
    if (!activos) return;
    const t = setInterval(() => {
      api.cuaMisiones().then(setMisiones).catch(() => {});
    }, 4000);
    return () => clearInterval(t);
  }, [activos]);

  const worker = caps.find((c) => c.capacidad === capSel) ?? null;

  const refrescarMisiones = () => api.cuaMisiones().then(setMisiones).catch(() => {});
  const refrescarRutinas = () => api.cuaRutinas().then(setRutinas).catch(() => {});

  // Despacha un encargo ahora (compositor o rutina guardada). Reusa el mismo encolar.
  const ejecutar = async (capacidad: string, texto: string, etiqueta: string) => {
    await api.cuaEncolar(capacidad, texto.trim() || undefined);
    toast(`Encargo despachado a ${etiqueta}.`, "info");
    await refrescarMisiones();
  };

  const ejecutarCompositor = async () => {
    if (!worker) return;
    setEnviando(true);
    try {
      await ejecutar(worker.capacidad, instruccion, worker.sistema);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setEnviando(false);
    }
  };

  const correrRutina = async (r: RutinaBackoffice) => {
    setCorriendoId(r.id);
    try {
      await ejecutar(r.capacidad, r.instruccion, r.nombre);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setCorriendoId(null);
    }
  };

  const guardarRutina = async () => {
    if (!worker || !nombreRutina.trim()) return;
    setGuardando(true);
    try {
      await api.cuaGuardarRutina({
        nombre: nombreRutina.trim(),
        capacidad: worker.capacidad,
        instruccion: instruccion.trim() || undefined,
      });
      toast(`Rutina guardada: "${nombreRutina.trim()}".`, "success");
      setNombreRutina("");
      setGuardarAbierto(false);
      await refrescarRutinas();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setGuardando(false);
    }
  };

  const borrarRutina = async (r: RutinaBackoffice) => {
    const ok = await confirm({
      title: "Borrar rutina",
      message: `Se borra "${r.nombre}". La bitácora de lo que ya corrió se conserva.`,
      confirmLabel: "Borrar",
    });
    if (!ok) return;
    try {
      await api.cuaBorrarRutina(r.id);
      await refrescarRutinas();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const enCurso = (misiones ?? []).filter(
    (m) => m.status === "queued" || m.status === "running",
  ).length;
  const conResultado = (misiones ?? []).filter((m) => m.status === "done").length;

  const cargado = misiones !== null && rutinas !== null;
  const listaRutinas = rutinas ?? [];
  const listaMisiones = misiones ?? [];
  const vacioTotal = cargado && listaRutinas.length === 0 && listaMisiones.length === 0;

  const stats = useMemo(
    () => [
      { label: "Rutinas guardadas", value: listaRutinas.length },
      { label: "Encargos despachados", value: listaMisiones.length },
      { label: "Con resultado", value: conResultado },
    ],
    [listaRutinas, listaMisiones, conResultado],
  );

  return (
    <div className="min-w-0">
      <PageHeader
        title="Rutinas"
        subtitle="Despacha un encargo a un asistente: dile a qué portal entrar (el SAT, tu banco, tribunales) y qué traerte. Entra por su cuenta, hace la consulta y te deja el resultado con evidencia. Guarda los que repites y córrelos con un clic."
      />

      {error ? (
        <ErrorState message={error} retry={cargar} />
      ) : !cargado ? (
        <div className="mx-auto max-w-3xl space-y-6">
          <Skeleton className="h-24 w-full rounded-lg" />
          <Skeleton className="h-40 w-full rounded-lg" />
        </div>
      ) : (
        <div className="reveal mx-auto max-w-3xl space-y-5">
          {/* ── LANZADOR (hero) ───────────────────────────────────────────────────
              El foco único: despachar un encargo. Trae adentro el aviso honesto, las
              cifras titulares y el acceso a Portales, para no alargar la página. */}
          <Lanzador
            caps={caps}
            worker={worker}
            capSel={capSel}
            onCap={(cap) => setCapSel(capSel === cap ? null : cap)}
            instruccion={instruccion}
            onInstruccion={setInstruccion}
            enviando={enviando}
            onEjecutar={ejecutarCompositor}
            guardarAbierto={guardarAbierto}
            onToggleGuardar={() => setGuardarAbierto((v) => !v)}
            nombreRutina={nombreRutina}
            onNombreRutina={setNombreRutina}
            guardando={guardando}
            onGuardar={guardarRutina}
            enseñar={vacioTotal}
            estado={estado}
            stats={stats}
            mostrarStats={!vacioTotal}
            onAbrirPortales={() => setPortalesAbierto(true)}
          />

          {/* ── RUTINAS GUARDADAS · ACTIVIDAD ─────────────────────────────────────
              Las dos vistas de "lo que ya existe" van tras un tab, no apiladas: las
              recetas de un clic y la bitácora en vivo. La insignia de Actividad avisa
              cuántos encargos siguen adentro del portal. */}
          <div>
            <Tabs
              tabs={[
                {
                  key: "rutinas",
                  label: "Rutinas guardadas",
                  count: listaRutinas.length || undefined,
                },
                { key: "actividad", label: "Actividad", count: enCurso || undefined },
              ]}
              active={tab}
              onChange={(k) => setTab(k as "rutinas" | "actividad")}
            />

            {tab === "rutinas" ? (
              !vacioTotal ? (
                <Recetas
                  rutinas={listaRutinas}
                  corriendoId={corriendoId}
                  onCorrer={correrRutina}
                  onBorrar={borrarRutina}
                />
              ) : (
                <p className="rounded-lg border border-dashed border-line-strong bg-surface px-4 py-3.5 text-[12px] leading-relaxed text-ink-3">
                  Aún no guardas rutinas. Despacha un encargo arriba y guárdalo con «Guardar como
                  rutina»; aquí queda listo para correr con un clic.
                </p>
              )
            ) : !vacioTotal && listaMisiones.length > 0 ? (
              <Bitacora misiones={listaMisiones} enCurso={enCurso} />
            ) : (
              <p className="text-[12px] text-ink-3">Aún no hay encargos despachados.</p>
            )}
          </div>
        </div>
      )}

      {/* Portales y accesos en un Drawer: registrar un portal por URL y conectar su
          acceso con el handoff de login (el dueño entra, el asistente reusa la sesión).
          Se abre desde el hero para no arrastrar la sección más grande hacia abajo. */}
      <Portales
        open={portalesAbierto}
        onClose={() => setPortalesAbierto(false)}
        caps={caps}
        estado={estado}
        onCambio={cargar}
      />

      {dialog}
    </div>
  );
}

// ── Lanzador ──────────────────────────────────────────────────────────────────
// Elige portal, describe el encargo, despacha o guárdalo como rutina. En estado
// vacío enseña el flujo (portal → describe → ejecuta → trae resultado) sin humo.
function Lanzador({
  caps,
  worker,
  capSel,
  onCap,
  instruccion,
  onInstruccion,
  enviando,
  onEjecutar,
  guardarAbierto,
  onToggleGuardar,
  nombreRutina,
  onNombreRutina,
  guardando,
  onGuardar,
  enseñar,
  estado,
  stats,
  mostrarStats,
  onAbrirPortales,
}: {
  caps: CuaCapacidad[];
  worker: CuaCapacidad | null;
  capSel: string | null;
  onCap: (cap: string) => void;
  instruccion: string;
  onInstruccion: (v: string) => void;
  enviando: boolean;
  onEjecutar: () => void;
  guardarAbierto: boolean;
  onToggleGuardar: () => void;
  nombreRutina: string;
  onNombreRutina: (v: string) => void;
  guardando: boolean;
  onGuardar: () => void;
  enseñar: boolean;
  estado: CuaEstado | null;
  stats: { label: string; value: number }[];
  mostrarStats: boolean;
  onAbrirPortales: () => void;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-line bg-surface elev-sm">
      <div className="border-b border-line/70 bg-panel/40 px-5 py-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
              <PortalIcon className="h-3.5 w-3.5 text-accent-ink" />
              Manda un encargo
            </h2>
            <p className="mt-0.5 text-[11.5px] text-ink-3">Tú despachas · el asistente ejecuta</p>
          </div>
          <button
            onClick={onAbrirPortales}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12px] font-medium text-accent-ink transition-colors hover:border-line-strong"
          >
            <PortalIcon className="h-3 w-3" />
            Portales y accesos
          </button>
        </div>

        {/* Cifras titulares en una tira compacta (no una tarjeta aparte hacia abajo). */}
        {mostrarStats && (
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-line/60 pt-3">
            {stats.map((s) => (
              <span key={s.label} className="inline-flex items-baseline gap-1.5">
                <AnimatedNumber
                  value={s.value}
                  className="tnum text-[16px] font-semibold leading-none text-ink"
                />
                <span className="text-[11px] text-ink-3">{s.label}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="p-5">
        {/* Aviso honesto, slim: si falta el navegador del asistente o la IA del negocio,
            todo encargo quedará en «No pudo». Avisa, no bloquea (el backend corta honesto). */}
        {estado && !estado.listo && (
          <div className="mb-4 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
            <span className="font-semibold text-warn">
              La oficina no puede operar portales todavía.
            </span>{" "}
            {!estado.navegador_listo ? (
              estado.navegador_detalle
            ) : (
              <>
                Falta conectar la IA de tu negocio en{" "}
                <a
                  href="/proveedor"
                  className="font-medium text-accent-ink underline-offset-2 hover:underline"
                >
                  Proveedor de IA
                </a>
                ; sin ella el asistente no puede entrar a ningún portal.
              </>
            )}{" "}
            Los encargos que despaches quedarán en «No pudo» con esta razón.
          </div>
        )}

        {caps.length === 0 ? (
          <p className="text-[12.5px] leading-relaxed text-ink-3">
            Aún no hay portales disponibles. Elige CUA como fuente de una capacidad en Integraciones
            para habilitarlos.
          </p>
        ) : (
          <>
            {/* Enseñanza honesta del flujo en una sola línea, solo cuando aún no hay nada. */}
            {enseñar && (
              <p className="mb-4 rounded-lg border border-line bg-bg px-3.5 py-2.5 text-[11.5px] leading-relaxed text-ink-3">
                Elige un portal, describe en tus palabras qué necesitas de ahí y despacha · entra por
                su cuenta en segundo plano y te deja el resultado con capturas de evidencia.
              </p>
            )}

            <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
              ¿A qué portal?
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {caps.map((c) => {
                const activo = capSel === c.capacidad;
                const detalle = !c.url_configurada
                  ? "Falta la dirección · ponla en Portales"
                  : c.tiene_sesion
                    ? "Acceso conectado"
                    : "Sin acceso · conéctalo en Portales";
                return (
                  <button
                    key={c.capacidad}
                    onClick={() => onCap(c.capacidad)}
                    aria-pressed={activo}
                    title={`${c.objetivo} · ${detalle}`}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                      activo
                        ? "border-accent bg-accent-soft/50 text-ink"
                        : "border-line bg-surface text-ink-2 hover:border-line-strong"
                    }`}
                  >
                    <span
                      aria-hidden
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        !c.url_configurada
                          ? "bg-warn"
                          : c.tiene_sesion
                            ? "bg-ok"
                            : "bg-ink-3/50"
                      }`}
                    />
                    {c.sistema}
                  </button>
                );
              })}
            </div>

            <Collapse open={worker !== null}>
              <div className="mt-4">
                <label
                  htmlFor="instruccion-tarea"
                  className="block text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3"
                >
                  ¿Qué necesitas que haga ahí?
                </label>
                <textarea
                  id="instruccion-tarea"
                  value={instruccion}
                  onChange={(e) => onInstruccion(e.target.value)}
                  rows={3}
                  placeholder={worker ? `Por ejemplo: ${worker.objetivo}` : ""}
                  className="mt-2 w-full resize-none rounded-md border border-line bg-surface px-3 py-2 text-[12.5px] leading-relaxed text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
                />
                <p className="mt-2 text-[11.5px] leading-relaxed text-ink-3">
                  Para un portal real (el SAT, tu banco), primero conecta el acceso en{" "}
                  <a
                    href="/integraciones"
                    className="font-medium text-accent-ink underline-offset-2 hover:underline"
                  >
                    Integraciones
                  </a>
                  ; el asistente ya sabe operarlo.
                </p>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <PrimaryButton
                    onClick={onEjecutar}
                    disabled={enviando}
                    className="inline-flex items-center gap-1.5"
                  >
                    <PlayIcon className="h-2.5 w-2.5" />
                    {enviando ? "Despachando…" : "Despachar ahora"}
                  </PrimaryButton>
                  <SecondaryButton onClick={onToggleGuardar} aria-expanded={guardarAbierto}>
                    Guardar como rutina
                  </SecondaryButton>
                </div>

                <Collapse open={guardarAbierto}>
                  <div className="mt-3 rounded-md border border-line bg-bg p-3">
                    <label
                      htmlFor="nombre-rutina"
                      className="block text-[11.5px] font-medium text-ink-2"
                    >
                      Ponle un nombre para repetirla luego
                    </label>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <input
                        id="nombre-rutina"
                        value={nombreRutina}
                        onChange={(e) => onNombreRutina(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") onGuardar();
                        }}
                        placeholder="Ej: Depósitos de la quincena"
                        className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
                      />
                      <PrimaryButton onClick={onGuardar} disabled={guardando || !nombreRutina.trim()}>
                        {guardando ? "Guardando…" : "Guardar"}
                      </PrimaryButton>
                    </div>
                    <p className="mt-1.5 text-[11px] text-ink-3">
                      Se guarda para repetirla con un clic; no la despacha ahora.
                    </p>
                  </div>
                </Collapse>
              </div>
            </Collapse>
          </>
        )}
      </div>
    </section>
  );
}

// ── Portales y accesos ─────────────────────────────────────────────────────────
// Registrar a qué sitio entrar (por URL) y CONECTAR su acceso con el handoff de login:
// se abre una ventana, el dueño entra él mismo (usuario, e.firma, 2FA — lo que sea) y su
// sesión ya autenticada se guarda cifrada para que el asistente arranque logueado. Nadie
// más que el dueño toca su contraseña. La ventana solo abre donde corre aiuda (su máquina);
// en la nube el aviso lo dice y no ofrece el botón.

// Muestra una URL legible (host + inicio de ruta), sin el http:// ni colas larguísimas.
function urlBonita(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname === "/" ? "" : u.pathname;
    return `${u.host}${path}`.replace(/\/$/, "").slice(0, 46);
  } catch {
    return url.slice(0, 46);
  }
}

const HANDOFF_VIVO = ["abriendo", "esperando", "guardando"];

function Portales({
  open,
  onClose,
  caps,
  estado,
  onCambio,
}: {
  open: boolean;
  onClose: () => void;
  caps: CuaCapacidad[];
  estado: CuaEstado | null;
  onCambio: () => void;
}) {
  const [agregar, setAgregar] = useState(false);
  const [nombre, setNombre] = useState("");
  const [url, setUrl] = useState("");
  const [notas, setNotas] = useState("");
  const [creando, setCreando] = useState(false);

  // Editor de dirección para un portal built-in (banca/tribunal) que aún no la tiene.
  const [editCap, setEditCap] = useState<string | null>(null);
  const [editUrl, setEditUrl] = useState("");
  const [guardandoUrl, setGuardandoUrl] = useState(false);

  // Handoff de login vivo (una a la vez): a qué portal y en qué estado va.
  const [sesion, setSesion] = useState<CuaSesionHandoff | null>(null);
  const [conectando, setConectando] = useState<string | null>(null);

  const { confirm, dialog } = useConfirm();

  const posible = estado?.handoff_posible ?? false;
  const gate = estado !== null && !estado.handoff_posible;

  // Sigue el handoff mientras esté vivo; al terminar avisa y refresca los accesos.
  useEffect(() => {
    if (!sesion || !HANDOFF_VIVO.includes(sesion.estado)) return;
    const t = setInterval(async () => {
      try {
        const s = await api.cuaEstadoSesion(sesion.id);
        setSesion(s);
        if (s.estado === "guardado") {
          toast("Acceso conectado. El asistente ya puede entrar por su cuenta.", "success");
          setSesion(null);
          onCambio();
        } else if (s.estado === "cancelado") {
          setSesion(null);
        } else if (s.estado === "error") {
          toast(s.detalle || "No se pudo conectar el acceso.", "error");
        }
      } catch {
        /* red intermitente: el siguiente tick reintenta */
      }
    }, 1500);
    return () => clearInterval(t);
  }, [sesion, onCambio]);

  const crear = async () => {
    if (!nombre.trim() || !url.trim()) return;
    setCreando(true);
    try {
      await api.cuaCrearPortal({
        nombre: nombre.trim(),
        url: url.trim(),
        notas: notas.trim() || undefined,
      });
      setNombre("");
      setUrl("");
      setNotas("");
      setAgregar(false);
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setCreando(false);
    }
  };

  const guardarUrl = async (cap: string) => {
    if (!editUrl.trim()) return;
    setGuardandoUrl(true);
    try {
      await api.cuaSetUrlBuiltin(cap, editUrl.trim());
      setEditCap(null);
      setEditUrl("");
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setGuardandoUrl(false);
    }
  };

  const conectar = async (cap: string) => {
    setConectando(cap);
    try {
      setSesion(await api.cuaIniciarSesion(cap));
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setConectando(null);
    }
  };

  const confirmarEntrada = async () => {
    if (!sesion) return;
    try {
      setSesion(await api.cuaConfirmarSesion(sesion.id));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const cancelarEntrada = async () => {
    if (!sesion) return;
    try {
      await api.cuaCancelarSesion(sesion.id);
    } catch {
      /* si ya no existe, igual la soltamos */
    }
    setSesion(null);
  };

  const olvidar = async (cap: string, sistema: string) => {
    const ok = await confirm({
      title: "Olvidar acceso",
      message: `Se borra la sesión guardada de "${sistema}". Tendrás que volver a entrar para reconectarlo.`,
      confirmLabel: "Olvidar",
    });
    if (!ok) return;
    try {
      await api.cuaOlvidarSesion(cap);
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const borrarPortal = async (cap: string, sistema: string) => {
    const ok = await confirm({
      title: "Borrar portal",
      message: `Se borra "${sistema}" y su acceso guardado. Los encargos que ya corrieron se conservan.`,
      confirmLabel: "Borrar",
    });
    if (!ok) return;
    try {
      await api.cuaBorrarPortal(cap.slice("portal:".length));
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        title="Portales y accesos"
        subtitle="Tú entras una vez · el asistente reusa tu sesión"
        size="lg"
      >
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[12px] leading-relaxed text-ink-3">
              Registra a qué sitio entrar y conéctale el acceso; después el asistente entra por su
              cuenta.
            </p>
            <button
              onClick={() => setAgregar((v) => !v)}
              aria-expanded={agregar}
              className="shrink-0 text-[12px] font-medium text-accent-ink transition-colors hover:text-accent-strong"
            >
              {agregar ? "Cancelar" : "Agregar portal"}
            </button>
          </div>
        {/* Alta de un portal a la medida por URL. */}
        <Collapse open={agregar}>
          <div className="rounded-lg border border-line bg-bg p-3.5">
            <div className="grid gap-2 sm:grid-cols-2">
              <input
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
                placeholder="Nombre (ej: Mi banco, Proveedor X)"
                className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
              />
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://portal.de-tu-negocio.mx/acceso"
                className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
              />
            </div>
            <input
              value={notas}
              onChange={(e) => setNotas(e.target.value)}
              placeholder="Notas para el asistente (opcional): cómo es el acceso, qué buscar…"
              className="mt-2 w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
            />
            <div className="mt-2.5 flex items-center gap-2">
              <PrimaryButton onClick={crear} disabled={creando || !nombre.trim() || !url.trim()}>
                {creando ? "Agregando…" : "Agregar portal"}
              </PrimaryButton>
              <span className="text-[11px] text-ink-3">
                Después conéctale el acceso: tú entras, el asistente reusa tu sesión.
              </span>
            </div>
          </div>
        </Collapse>

        {/* Panel del handoff vivo: la ventana abierta esperando a que el dueño entre. */}
        {sesion && (
          <div className="rounded-lg border border-accent/45 bg-accent-soft/40 px-4 py-3.5">
            {sesion.estado === "abriendo" && (
              <p className="text-[12.5px] text-ink-2">
                Abriendo la ventana de «{sesion.sistema}»…
              </p>
            )}
            {sesion.estado === "esperando" && (
              <div>
                <p className="text-[13px] font-semibold text-ink">
                  Se abrió una ventana con «{sesion.sistema}»
                </p>
                <p className="mt-1 text-[12px] leading-relaxed text-ink-2">
                  Entra como siempre (usuario, e.firma, 2FA — lo que uses). Cuando ya estés
                  dentro, dale «Ya entré» y guardamos tu sesión. Tu contraseña no se guarda
                  ni la vemos.
                </p>
                <div className="mt-3 flex items-center gap-2">
                  <PrimaryButton onClick={confirmarEntrada}>Ya entré</PrimaryButton>
                  <SecondaryButton onClick={cancelarEntrada}>Cancelar</SecondaryButton>
                </div>
              </div>
            )}
            {sesion.estado === "guardando" && (
              <p className="text-[12.5px] text-ink-2">Guardando tu sesión…</p>
            )}
            {(sesion.estado === "error" || sesion.estado === "expirado") && (
              <div>
                <p className="text-[12.5px] text-danger">
                  {sesion.detalle ||
                    (sesion.estado === "expirado"
                      ? "Se agotó el tiempo para entrar."
                      : "No se pudo conectar el acceso.")}
                </p>
                <button
                  onClick={() => setSesion(null)}
                  className="mt-2 text-[12px] font-medium text-accent-ink hover:text-accent-strong"
                >
                  Cerrar
                </button>
              </div>
            )}
          </div>
        )}

        {/* Aviso honesto cuando esta máquina no puede abrir la ventana (la nube). */}
        {gate && (
          <p className="rounded-lg border border-warn/40 bg-warn-soft px-3.5 py-2.5 text-[12px] leading-relaxed text-ink-2">
            <span className="font-semibold text-warn">Para conectar accesos, aiuda debe correr en tu máquina.</span>{" "}
            {estado?.handoff_detalle} La ventana del navegador se abre donde corre aiuda;
            desde la nube no hay pantalla donde entres tú.
          </p>
        )}

        {/* La lista de portales: built-in + a la medida, con su acceso. */}
        <ul className="space-y-2">
          {caps.map((c) => (
            <li
              key={c.capacidad}
              className="rounded-lg border border-line bg-surface px-3.5 py-3"
            >
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-ink">{c.sistema}</p>
                  {c.url_configurada ? (
                    <p className="tnum truncate text-[11px] text-ink-3">{urlBonita(c.url)}</p>
                  ) : (
                    <p className="text-[11px] text-warn">Falta la dirección del portal.</p>
                  )}
                </div>
                {c.url_configurada &&
                  (c.tiene_sesion ? (
                    <span className="shrink-0 rounded bg-ok/15 px-1.5 py-0.5 text-[10.5px] font-medium text-ok">
                      Acceso conectado
                    </span>
                  ) : (
                    <span className="shrink-0 rounded bg-line/60 px-1.5 py-0.5 text-[10.5px] font-medium text-ink-3">
                      Sin conectar
                    </span>
                  ))}
              </div>

              {/* Editor de dirección para un built-in sin URL (la banca/el tribunal es tuyo). */}
              {!c.url_configurada && !c.editable && (
                <div className="mt-2.5">
                  {editCap === c.capacidad ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        value={editUrl}
                        onChange={(e) => setEditUrl(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") guardarUrl(c.capacidad);
                        }}
                        autoFocus
                        placeholder="https://portal…"
                        className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
                      />
                      <PrimaryButton
                        onClick={() => guardarUrl(c.capacidad)}
                        disabled={guardandoUrl || !editUrl.trim()}
                      >
                        {guardandoUrl ? "Guardando…" : "Guardar"}
                      </PrimaryButton>
                      <button
                        onClick={() => {
                          setEditCap(null);
                          setEditUrl("");
                        }}
                        className="text-[12px] text-ink-3 hover:text-ink"
                      >
                        Cancelar
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => {
                        setEditCap(c.capacidad);
                        setEditUrl("");
                      }}
                      className="text-[12px] font-medium text-accent-ink hover:text-accent-strong"
                    >
                      Poner la dirección
                    </button>
                  )}
                </div>
              )}

              {/* Acciones de acceso. */}
              <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                {posible && c.url_configurada && (
                  <button
                    onClick={() => conectar(c.capacidad)}
                    disabled={conectando === c.capacidad || sesion !== null}
                    className="text-[12px] font-medium text-accent-ink transition-colors hover:text-accent-strong disabled:opacity-50"
                  >
                    {conectando === c.capacidad
                      ? "Abriendo…"
                      : c.tiene_sesion
                        ? "Reconectar acceso"
                        : "Conectar acceso (entras tú)"}
                  </button>
                )}
                {c.tiene_sesion && (
                  <button
                    onClick={() => olvidar(c.capacidad, c.sistema)}
                    className="text-[12px] text-ink-3 transition-colors hover:text-danger"
                  >
                    Olvidar acceso
                  </button>
                )}
                {c.editable && (
                  <button
                    onClick={() => borrarPortal(c.capacidad, c.sistema)}
                    className="ml-auto text-[12px] text-ink-3 transition-colors hover:text-danger"
                  >
                    Borrar portal
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
        </div>
      </Drawer>
      {dialog}
    </>
  );
}

// ── Recetas ───────────────────────────────────────────────────────────────────
// Rutinas guardadas como tarjetas compactas de un clic. Correr = despacha; borrar
// = confirma. Sin cadencia: no hay "cada día"; se corre cuando tú quieras.
function Recetas({
  rutinas,
  corriendoId,
  onCorrer,
  onBorrar,
}: {
  rutinas: RutinaBackoffice[];
  corriendoId: string | null;
  onCorrer: (r: RutinaBackoffice) => void;
  onBorrar: (r: RutinaBackoffice) => void;
}) {
  return (
    <section>
      <div className="mb-2.5 flex items-baseline justify-between gap-3">
        <h2 className="text-[13px] font-semibold text-ink">Rutinas guardadas</h2>
        {rutinas.length > 0 ? (
          <span className="tnum text-[11.5px] text-ink-3">
            {rutinas.length} · córrelas con un clic
          </span>
        ) : (
          <span className="text-[11.5px] text-ink-3">Córrelas con un clic</span>
        )}
      </div>

      {rutinas.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-strong bg-surface px-4 py-3.5 text-[12px] leading-relaxed text-ink-3">
          Aún no guardas ninguna. Cuando un encargo lo repitas seguido (por ejemplo: entra al banco y
          tráeme los depósitos del periodo), guárdalo arriba con «Guardar como rutina» y aquí queda
          listo para correr con un clic.
        </p>
      ) : (
        <ul className="reveal-stagger grid gap-2 sm:grid-cols-2">
          {rutinas.map((r) => (
            <RecetaCard
              key={r.id}
              r={r}
              corriendo={corriendoId === r.id}
              onCorrer={() => onCorrer(r)}
              onBorrar={() => onBorrar(r)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function RecetaCard({
  r,
  corriendo,
  onCorrer,
  onBorrar,
}: {
  r: RutinaBackoffice;
  corriendo: boolean;
  onCorrer: () => void;
  onBorrar: () => void;
}) {
  return (
    <li className="flex items-center gap-3 rounded-lg border border-line bg-surface px-3.5 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ink-3">
          {r.sistema}
        </p>
        <p className="mt-0.5 truncate text-[13px] font-medium text-ink">{r.nombre}</p>
        <p className="mt-0.5 truncate text-[11.5px] text-ink-3">
          {r.instruccion || "Con la instrucción por defecto del portal."}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <SecondaryButton
          onClick={onCorrer}
          disabled={corriendo}
          className="inline-flex items-center gap-1.5"
        >
          <PlayIcon className="h-2.5 w-2.5" />
          {corriendo ? "Despachando…" : "Correr"}
        </SecondaryButton>
        <button
          onClick={onBorrar}
          aria-label={`Borrar rutina ${r.nombre}`}
          title="Borrar rutina"
          className="rounded p-1.5 text-ink-3 transition-colors hover:bg-danger-soft hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger"
        >
          <svg viewBox="0 0 14 14" className="h-3.5 w-3.5" fill="none" aria-hidden="true">
            <path
              d="M3 4h8M5.5 4V2.8h3V4M4.2 4l.5 7.2h4.6L9.8 4"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
    </li>
  );
}

// ── Bitácora de actividad ───────────────────────────────────────────────────────
// Dos tiempos: EN CURSO (lo que el asistente hace ahora mismo, con pulso y sus pasos
// en vivo) y la LÍNEA DE TIEMPO de lo terminado, con evidencia. No es un tablero de
// columnas: es un feed cronológico. Se lee de un vistazo qué pasa adentro del portal.
function Bitacora({ misiones, enCurso }: { misiones: CuaMision[]; enCurso: number }) {
  const [todo, setTodo] = useState(false);
  const TOPE = 6;

  const vivas = misiones
    .filter((m) => m.status === "queued" || m.status === "running")
    // running antes que queued; dentro, lo más reciente arriba.
    .sort((a, b) => {
      if (a.status !== b.status) return a.status === "running" ? -1 : 1;
      return (cuando(b) ?? "").localeCompare(cuando(a) ?? "");
    });
  const terminadas = misiones
    .filter((m) => m.status === "done" || m.status === "failed")
    .sort((a, b) => (cuando(b) ?? "").localeCompare(cuando(a) ?? ""));

  const visibles = todo ? terminadas : terminadas.slice(0, TOPE);

  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-[13px] font-semibold text-ink">Bitácora de actividad</h2>
        {enCurso > 0 && (
          <span className="flex items-center gap-1.5 text-[11.5px] font-medium text-accent-ink">
            <span className="breathe h-1.5 w-1.5 rounded-full bg-accent" />
            {enCurso} adentro del portal
          </span>
        )}
      </div>

      {/* EN CURSO: prominente, con pulso y pasos en vivo. */}
      {vivas.length > 0 && (
        <div className="mb-6 space-y-2">
          {vivas.map((m) => (
            <MisionViva key={m.id} m={m} />
          ))}
        </div>
      )}

      {/* LÍNEA DE TIEMPO: lo terminado, en orden, con evidencia al expandir. */}
      {terminadas.length > 0 ? (
        <>
          {vivas.length > 0 && (
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
              Historial
            </p>
          )}
          <ol className="relative">
            {/* Riel de la línea de tiempo: hairline continuo; los nodos lo enmascaran. */}
            <span
              aria-hidden
              className="pointer-events-none absolute left-[7.5px] top-3 bottom-3 w-px bg-line"
            />
            {visibles.map((m) => (
              <MisionTerminada key={m.id} m={m} />
            ))}
          </ol>
          {terminadas.length > TOPE && (
            <button
              onClick={() => setTodo((v) => !v)}
              className="mt-3 text-[12px] font-medium text-accent-ink transition-colors hover:text-accent-strong"
            >
              {todo ? "Ver menos" : `Ver todas (${terminadas.length})`}
            </button>
          )}
        </>
      ) : (
        vivas.length === 0 && (
          <p className="text-[12px] text-ink-3">Aún no hay encargos despachados.</p>
        )
      )}
    </section>
  );
}

// Una misión viva (en cola o adentro del portal): sin colapsar, todo a la vista, con
// sus pasos actualizándose. Es el foco "qué está pasando ahora".
function MisionViva({ m }: { m: CuaMision }) {
  const est = ESTADO[m.status];
  const instruccion = instruccionDe(m);
  const corriendo = m.status === "running";
  // En vivo mostramos los pasos recientes (los últimos son los más frescos).
  const pasos = m.steps.slice(-4);

  return (
    <div
      className={`rounded-lg border bg-surface px-4 py-3.5 ${
        corriendo ? "border-accent/40" : "border-line"
      }`}
    >
      <div className="flex items-center gap-3">
        <span
          className={`breathe shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ${est.cls}`}
        >
          {est.label}
        </span>
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">
          {m.sistema}
        </span>
        <span className="shrink-0 text-[11px] tabular-nums text-ink-3">
          {corriendo
            ? `empezó ${haceTiempo(m.startedAt || m.createdAt)}`
            : haceTiempo(m.createdAt)}
        </span>
      </div>

      <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-2">
        {m.resumen ||
          instruccion ||
          (corriendo ? "Trabajando en el portal…" : "En espera de turno.")}
      </p>

      {pasos.length > 0 && (
        <ul className="mt-2.5 space-y-1 border-t border-line/60 pt-2.5">
          {pasos.map((s, i) => {
            const ultimo = corriendo && i === pasos.length - 1;
            return (
              <li
                key={i}
                className={`flex items-start gap-2 truncate text-[11.5px] ${
                  ultimo ? "text-ink-2" : "text-ink-3"
                }`}
              >
                <span
                  className={`mt-1.5 h-1 w-1 shrink-0 rounded-full ${
                    ultimo ? "breathe bg-accent" : "bg-ink-3/50"
                  }`}
                />
                <span className="truncate">{s}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// Una misión terminada en la línea de tiempo: nodo + tarjeta expandible con lo que
// pediste, lo que trajo, el paso a paso y las capturas (cargadas al abrir).
function MisionTerminada({ m }: { m: CuaMision }) {
  const [abierto, setAbierto] = useState(false);
  const [evidencia, setEvidencia] = useState<string[] | null>(null);
  const [cargando, setCargando] = useState(false);
  const est = ESTADO[m.status];
  const instruccion = instruccionDe(m);

  const toggle = async () => {
    const next = !abierto;
    setAbierto(next);
    if (next && evidencia === null && m.evidencia_capturas > 0) {
      setCargando(true);
      try {
        setEvidencia((await api.cuaMision(m.id)).evidencia ?? []);
      } catch (e) {
        // No lo tragues: si la evidencia no baja, dilo (y deja reintentar al reabrir).
        toast(`No se pudo cargar la evidencia: ${(e as Error).message}`, "error");
      } finally {
        setCargando(false);
      }
    }
  };

  return (
    <li className="relative pb-3 pl-7 last:pb-0">
      {/* Nodo de la línea de tiempo: enmascara el riel con su halo del color de fondo. */}
      <span
        aria-hidden
        className={`absolute left-[3px] top-[15px] h-2.5 w-2.5 rounded-full ring-4 ring-bg ${est.dot}`}
      />
      <div className="overflow-hidden rounded-lg border border-line bg-surface">
        <button
          onClick={toggle}
          className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-panel/40 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
          aria-expanded={abierto}
        >
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ${est.cls}`}>
            {est.label}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-ink">{m.sistema}</span>
            <span className="block truncate text-[11.5px] text-ink-3">
              {m.status === "failed" ? m.error : m.resumen || instruccion || "Sin detalle."}
            </span>
          </span>
          {m.evidencia_capturas > 0 && (
            <span className="shrink-0 text-[11px] text-ink-3" title="Capturas de evidencia">
              {m.evidencia_capturas} capt.
            </span>
          )}
          <span className="shrink-0 text-[11px] tabular-nums text-ink-3">{fechaHora(cuando(m))}</span>
          <svg
            viewBox="0 0 12 12"
            className={`h-3 w-3 shrink-0 text-ink-3 transition-transform ${abierto ? "rotate-180" : ""}`}
            fill="none"
          >
            <path
              d="m3 4.5 3 3 3-3"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </button>

        <Collapse open={abierto}>
          <div className="border-t border-line/60 px-4 py-3 text-[12px]">
            {instruccion && (
              <div className="mb-3">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                  Le pediste
                </p>
                <p className="rounded-md border border-line/70 bg-bg px-3 py-2 text-[12px] leading-relaxed text-ink-2">
                  {instruccion}
                </p>
              </div>
            )}
            {m.status === "done" &&
              Object.keys(m.data ?? {}).some((k) => k !== "_instruccion") && (
                <div className="mb-3">
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                    Lo que trajo
                  </p>
                  <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-line/70 bg-bg px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
                    {JSON.stringify(
                      Object.fromEntries(
                        Object.entries(m.data ?? {}).filter(([k]) => k !== "_instruccion"),
                      ),
                      null,
                      2,
                    )}
                  </pre>
                </div>
              )}
            {m.status === "failed" && m.error && (
              <p className="mb-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-[11.5px] text-danger">
                {m.error}
              </p>
            )}
            {m.steps.length > 0 && (
              <div className="mb-3">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                  Paso a paso
                </p>
                <ul className="space-y-0.5">
                  {m.steps.map((s, i) => (
                    <li key={i} className="truncate text-[11.5px] text-ink-3">
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {m.evidencia_capturas > 0 && (
              <div>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                  Evidencia ({m.evidencia_capturas})
                </p>
                {cargando ? (
                  <Skeleton className="h-24 w-full rounded-md" />
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {(evidencia ?? []).map((b64, i) => (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        key={i}
                        src={`data:image/png;base64,${b64}`}
                        alt={`captura ${i + 1}`}
                        className="h-24 w-auto rounded border border-line"
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </Collapse>
      </div>
    </li>
  );
}
