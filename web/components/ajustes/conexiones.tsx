"use client";

import { fechaHora, instante } from "@/lib/format";

/**
 * Ajustes > Conexiones: UNA lista.
 *
 * Arriba lo que ya está conectado; luego lo que ya se estrenó con cuentas reales
 * (WhatsApp, Excel, Odoo, el SAT) y el Correo; y al final, bajo un solo
 * encabezado cerrado, lo que nadie ha usado todavía con una cuenta real. Antes
 * eran 25 tarjetas en tres vistas para 15 conexiones, con el sello "Sin
 * estrenar" repetido doce veces.
 *
 * "Conectado" lo decide el servidor y quiere decir una sola cosa: hay
 * credenciales guardadas o una sesión viva. Que existan datos que vinieron de
 * un sistema no lo vuelve conectado.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api, type CustomConnector, type IntegrationNode } from "@/lib/api";
import {
  ErrorState,
  SIN_ESTRENAR_NOTA,
  SecondaryButton,
  SinEstrenar,
  Skeleton,
  useApi,
  Estado,
  QuietButton,
} from "@/components/ui";
import { IntegrationConfigDrawer } from "@/components/integration-config-drawer";
import { CAP_LABEL, CustomConnectorDrawer } from "@/components/custom-connector-drawer";
import { toast } from "@/components/toast";

/** Lo que no se conecta con un panel: tiene su propia pantalla. */
const DESTINO: Record<string, { href: string; accion: string }> = {
  excel: { href: "/importar", accion: "Subir archivo" },
  sat: { href: "/sat", accion: "Abrir" },
};

function Logo({ node }: { node: IntegrationNode }) {
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-fill">
      {node.logo ? (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img src={node.logo} alt="" className="h-5 w-5 object-contain" />
      ) : (
        <span className="text-rotulo font-semibold text-ink-2">{node.name.slice(0, 2)}</span>
      )}
    </span>
  );
}

function Flecha() {
  return (
    <svg viewBox="0 0 12 12" className="h-3 w-3 shrink-0 text-ink-3" fill="none" aria-hidden="true">
      <path d="m4.5 3 3 3-3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function registros(n: number): string {
  return `${n.toLocaleString("es-MX")} ${n === 1 ? "registro" : "registros"}`;
}

/** Un renglón de la lista. El estado se dice con palabras; el color va solo en el punto. */
function Fila({
  node,
  sello,
  onOpen,
}: {
  node: IntegrationNode;
  /** El sello "Sin estrenar" solo en lo que queda FUERA del grupo cerrado (Correo). */
  sello: boolean;
  onOpen: (n: IntegrationNode) => void;
}) {
  const destino = DESTINO[node.key];
  const estado =
    node.verified === "error" ? (
      <span
        className="mark"
        title={node.last_error ?? undefined}
        style={{ "--mark": "var(--color-danger)" } as React.CSSProperties}
      >
        Revisar
      </span>
    ) : node.connected ? (
      <Estado tono="ok">
        Conectado
      </Estado>
    ) : (
      <span className="text-apoyo font-medium text-accent-ink">{destino?.accion ?? "Conectar"}</span>
    );

  const cuerpo = (
    <>
      <Logo node={node} />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <span className="text-cuerpo font-medium text-ink">{node.name}</span>
          {sello && !node.estrenada && <SinEstrenar />}
        </span>
        <span className="block text-apoyo text-ink-3">
          {node.rol}
          {node.records > 0 ? ` · ${registros(node.records)}` : ""}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-2.5">
        {estado}
        <Flecha />
      </span>
    </>
  );

  const cls =
    "-mx-3 flex w-[calc(100%+1.5rem)] items-center gap-3.5 rounded-lg px-3 py-3 text-left hover:bg-fill";
  return (
    <li>
      {destino ? (
        <Link href={destino.href} className={cls}>
          {cuerpo}
        </Link>
      ) : (
        <button type="button" onClick={() => onOpen(node)} className={cls}>
          {cuerpo}
        </button>
      )}
    </li>
  );
}

/** Semáforo honesto de una conexión a la medida: la última lectura y el último Probar. */
function EstadoPropia({ c }: { c: CustomConnector }) {
  // Manda la señal MÁS RECIENTE: si acabas de probarla y funciona, el error de una
  // lectura vieja ya no dice "Revisar" (y al revés).
  const probada = instante(c.last_test_at)?.getTime() ?? 0;
  const leida = instante(c.last_sync_at)?.getTime() ?? 0;
  const testEsMasReciente = probada > 0 && probada > leida;
  const falla = testEsMasReciente ? c.last_test_ok === false : Boolean(c.last_error);
  if (falla) {
    return (
      <span
        className="mark"
        title={(testEsMasReciente ? c.last_test_error : c.last_error) || undefined}
        style={{ "--mark": "var(--color-danger)" } as React.CSSProperties}
      >
        Revisar
      </span>
    );
  }
  if (!c.has_secret && c.auth_type) {
    return (
      <Estado tono="aviso">
        Falta tu clave
      </Estado>
    );
  }
  if (c.last_sync_at && !c.last_error) {
    return (
      <span
        className="mark"
        title={`Última lectura: ${fechaHora(c.last_sync_at)}`}
        style={{ "--mark": "var(--color-ok)" } as React.CSSProperties}
      >
        Leyó {registros(c.last_count ?? 0)}
      </span>
    );
  }
  if (c.last_test_ok) {
    return (
      <Estado tono="ok">
        Probada
      </Estado>
    );
  }
  return <Estado>Sin probar</Estado>;
}

/** Lo que aiuda REGRESÓ a tus sistemas. Solo aparece cuando hay algo que decir: un
 *  pago que no se pudo asentar en Odoo no debe quedarse callado dentro de la ficha
 *  de esa factura. */
function LoQueRegreso() {
  const { data, error, refetch } = useApi(() => api.writeback({}), []);
  const entries = data?.entries ?? [];
  if (error || entries.length === 0) return null;

  const fallidas = entries.filter((e) => e.estado === "falló");
  const pendientes = entries.filter((e) => e.estado === "pendiente");
  const asentadas = entries.length - fallidas.length - pendientes.length;
  const partes = [
    asentadas > 0 ? `${asentadas} ${asentadas === 1 ? "asentado" : "asentados"}` : "",
    pendientes.length > 0 ? `${pendientes.length} en espera` : "",
    fallidas.length > 0
      ? `${fallidas.length} que no ${fallidas.length === 1 ? "se pudo" : "se pudieron"} asentar`
      : "",
  ].filter(Boolean);

  return (
    <section className="mt-12">
      <h2 className="text-seccion font-semibold text-ink">Lo que regresó a tus sistemas</h2>
      <p className="mt-1 text-cuerpo text-ink-2">
        Lo que confirmas aquí se asienta en el sistema de donde vino: {partes.join(", ")}.
      </p>
      {/* Lo que falló es lo único que necesita al dueño. */}
      {fallidas.length > 0 && (
        <ul className="mt-3 divide-y divide-line border-y border-line">
          {fallidas.slice(0, 5).map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-3 text-cuerpo">
              <span className="font-medium text-ink">{e.target_label ?? e.target}</span>
              <span className="text-ink-2">{e.folio ?? e.action.replace(/_/g, " ")}</span>
              <Estado tono="falla">
                {e.last_error ?? "No se pudo asentar"}
              </Estado>
              <SecondaryButton
                size="sm"
                className="ml-auto"
                onClick={async () => {
                  try {
                    await api.retryWriteback(e.id);
                    toast("Reintentando.", "info");
                    refetch();
                  } catch (err) {
                    toast((err as Error).message, "error");
                  }
                }}
              >
                Reintentar
              </SecondaryButton>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AjustesConexiones({
  abrir,
  onCerrarPanel,
}: {
  /** Llave de la conexión cuyo panel debe abrirse al llegar (`?abrir=odoo`). */
  abrir?: string | null;
  /** El panel que vino abierto por la dirección se cerró: quien monta limpia la URL. */
  onCerrarPanel?: () => void;
}) {
  const { data, error, loading, refetch, refetchQuiet } = useApi(() => api.integrations(), []);
  const { data: propias, refetch: recargarPropias } = useApi(() => api.listCustomConnectors(), []);
  const [open, setOpen] = useState<IntegrationNode | null>(null);
  const [verOtras, setVerOtras] = useState(false);
  const [crear, setCrear] = useState(false);
  const [editar, setEditar] = useState<CustomConnector | null>(null);
  const [probando, setProbando] = useState<string | null>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const yaAbrio = useRef<string | null>(null);

  const systems = useMemo(() => data?.systems ?? [], [data]);
  const custom = propias ?? [];

  // Llegó con `?abrir=…`: se abre ese panel una vez, cuando el catálogo ya cargó.
  useEffect(() => {
    if (!abrir || yaAbrio.current === abrir || systems.length === 0) return;
    yaAbrio.current = abrir;
    const nodo = systems.find((s) => s.key === abrir);
    if (nodo) setOpen(nodo);
    else onCerrarPanel?.();
  }, [abrir, systems, onCerrarPanel]);

  // El panel enseña el estado del nodo: tras guardar o vincular, se le pasa el fresco.
  const abierto = open ? (systems.find((s) => s.key === open.key) ?? open) : null;

  function cerrarPanel() {
    setOpen(null);
    if (abrir) onCerrarPanel?.();
  }

  // Unas credenciales guardadas cuya última prueba falló no son una conexión: van
  // arriba de lo que falta, diciendo "Revisar", y no se cuentan como conectadas.
  const funciona = (s: IntegrationNode) => s.connected && s.verified !== "error";
  const conectadas = systems.filter(funciona);
  const porRevisar = systems.filter((s) => s.connected && !funciona(s));
  const principales = [
    ...porRevisar,
    ...systems
      .filter((s) => !s.connected && (s.estrenada || s.key === "email"))
      .sort((a, b) => Number(b.estrenada) - Number(a.estrenada)),
  ];
  const otras = systems.filter((s) => !s.connected && !s.estrenada && s.key !== "email");

  async function quitarPropia(id: string) {
    try {
      await api.deleteCustomConnector(id);
      recargarPropias();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  async function probarPropia(c: CustomConnector) {
    setProbando(c.id);
    try {
      const r = await api.retestCustomConnector(c.id);
      if (r.ok) toast(`${c.name}: funciona, leyó ${registros(r.count)} de muestra`, "info");
      else toast(`${c.name}: ${r.error}`, "error");
      recargarPropias();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setProbando(null);
    }
  }

  async function exportarPropia(c: CustomConnector) {
    try {
      const archivo = await api.exportCustomConnector(c.id);
      const blob = new Blob([JSON.stringify(archivo, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `conexion-${c.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  async function importarPropia(file: File) {
    try {
      const archivo = JSON.parse(await file.text()) as Record<string, unknown>;
      const creada = await api.importCustomConnector(archivo);
      toast("Conexión importada. Agrega tu clave y pruébala.", "info");
      recargarPropias();
      setEditar(creada); // directo a capturar la clave y probar
    } catch (e) {
      toast(
        e instanceof SyntaxError
          ? "Ese archivo no es una conexión exportada de aiuda."
          : (e as Error).message,
        "error",
      );
    }
  }

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <div className="max-w-3xl">
      <p className="mb-8 max-w-2xl text-cuerpo leading-relaxed text-ink-2">
        De dónde lee aiuda y por dónde escribe. Tus sistemas siguen mandando: aiuda trabaja encima
        de ellos.
      </p>

      {loading && !data ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      ) : (
        <>
          {conectadas.length > 0 && (
            <section className="mb-9">
              <h2 className="eyebrow">
                {conectadas.length === 1 ? "1 conectada" : `${conectadas.length} conectadas`}
              </h2>
              <ul className="mt-2 divide-y divide-line">
                {conectadas.map((n) => (
                  <Fila key={n.key} node={n} sello onOpen={setOpen} />
                ))}
              </ul>
            </section>
          )}

          <section>
            <h2 className="eyebrow">
              {conectadas.length > 0 ? "por conectar" : "nada conectado todavía"}
            </h2>
            <ul className="mt-2 divide-y divide-line">
              {principales.map((n) => (
                <Fila key={n.key} node={n} sello onOpen={setOpen} />
              ))}
            </ul>
          </section>

          {otras.length > 0 && (
            <section className="mt-6 border-t border-line pt-3">
              <button
                type="button"
                aria-expanded={verOtras}
                onClick={() => setVerOtras((v) => !v)}
                className="-mx-3 flex w-[calc(100%+1.5rem)] items-center gap-3 rounded-lg px-3 py-3 text-left hover:bg-fill"
              >
                <span className="min-w-0 flex-1 text-cuerpo font-medium text-ink">
                  {otras.length === 1 ? "Otra, sin estrenar" : `Otras ${otras.length}, sin estrenar`}
                </span>
                <span className="text-apoyo text-ink-3">{verOtras ? "Ocultar" : "Ver"}</span>
                <svg
                  viewBox="0 0 12 12"
                  className={`h-3 w-3 shrink-0 text-ink-3 transition-transform ${verOtras ? "rotate-90" : ""}`}
                  fill="none"
                  aria-hidden="true"
                >
                  <path d="m4.5 3 3 3-3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {verOtras && (
                <div className="reveal">
                  <p className="mb-1 mt-1 max-w-2xl text-apoyo leading-relaxed text-ink-3">
                    {SIN_ESTRENAR_NOTA} Puedes conectarlas; si algo falla, aquí mismo te lo decimos.
                  </p>
                  <ul className="divide-y divide-line">
                    {otras.map((n) => (
                      <Fila key={n.key} node={n} sello={false} onOpen={setOpen} />
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}
        </>
      )}

      <LoQueRegreso />

      {/* La salida de escape, al final: solo la necesita quien no encontró su sistema. */}
      <section className="mt-12">
        <div className="flex flex-wrap items-end justify-between gap-x-5 gap-y-3">
          <div className="min-w-0">
            <h2 className="text-seccion font-semibold text-ink">¿No está tu sistema?</h2>
            <p className="mt-1 max-w-xl text-cuerpo text-ink-2">
              Si tu sistema tiene una API, quien te ayuda con la computadora puede conectarlo
              aquí. aiuda lo lee cada hora, igual que a los demás.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <SecondaryButton onClick={() => setCrear(true)}>Crear una conexión</SecondaryButton>
            <QuietButton
              type="button"
              onClick={() => importRef.current?.click()}
              title="Carga una conexión que alguien te compartió (un archivo sin claves)"
            >
              Importar
            </QuietButton>
          </div>
        </div>
        <input
          ref={importRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) importarPropia(f);
            e.target.value = ""; // permite volver a importar el mismo archivo
          }}
        />

        {custom.length > 0 && (
          <ul className="mt-4 divide-y divide-line border-y border-line">
            {custom.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-cuerpo font-medium text-ink">
                    {c.name}
                    <span className="ml-2 font-normal text-ink-3">{CAP_LABEL[c.cap] ?? c.cap}</span>
                    {c.write_path && (
                      <span className="ml-2 font-normal text-ink-3">· también recibe altas</span>
                    )}
                  </p>
                  <p className="truncate text-apoyo text-ink-3">{c.base_url}</p>
                </div>
                <EstadoPropia c={c} />
                <div className="flex shrink-0 items-center gap-1">
                  <QuietButton
                    onClick={() => probarPropia(c)}
                    disabled={probando === c.id}
 size="sm"
>
                    {probando === c.id ? "Probando…" : "Probar"}
                  </QuietButton>
                  <QuietButton onClick={() => setEditar(c)} size="sm">
                    Editar
                  </QuietButton>
                  <QuietButton
                    onClick={() => exportarPropia(c)}
                    title="Descarga esta conexión (sin claves) para compartirla"
 size="sm"
>
                    Exportar
                  </QuietButton>
                  <QuietButton onClick={() => quitarPropia(c.id)} size="sm">
                    Quitar
                  </QuietButton>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <IntegrationConfigDrawer node={abierto} onClose={cerrarPanel} onSaved={refetchQuiet} />
      <CustomConnectorDrawer
        open={crear || editar !== null}
        cap=""
        editar={editar}
        onClose={() => {
          setCrear(false);
          setEditar(null);
        }}
        onSaved={recargarPropias}
      />
    </div>
  );
}
