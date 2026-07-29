"use client";

import { Suspense, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, type CustomConnector, type IntegrationNode } from "@/lib/api";
import { ErrorState, PageHeader, Skeleton, Tabs, useApi } from "@/components/ui";
import { IntegrationConfigDrawer } from "@/components/integration-config-drawer";
import { CAP_LABEL, CustomConnectorDrawer } from "@/components/custom-connector-drawer";
import { toast } from "@/components/toast";
import { Organigrama } from "@/components/organigrama";

// Conectores agrupados por INTENCIÓN (qué quieres lograr), no por tipo de conector. Cada
// necesidad mapea a una capacidad del backend; los conectores que la proveen son sus opciones.
// Un mismo conector puede servir a varias necesidades (Odoo trae cartera Y catálogo Y clientes),
// y así debe ser: entras por la necesidad, ves solo lo relevante, y creas el tuyo si falta.
const NEEDS: { cap: string; title: string; hint: string }[] = [
  { cap: "mensajeria", title: "Habla con tus clientes", hint: "El canal por donde les escribes: WhatsApp o correo." },
  { cap: "cuentas_por_cobrar", title: "Trae tu cartera", hint: "Tus facturas y pedidos con saldo por cobrar." },
  { cap: "cfdi", title: "Conecta tus CFDIs", hint: "Tus comprobantes del SAT como respaldo fiscal." },
  { cap: "confirmacion_pago", title: "Conecta tu banco", hint: "Para confirmar que un pago entró: banco o pasarela." },
  { cap: "directorio_clientes", title: "Tu directorio de clientes", hint: "El maestro de clientes y contactos." },
  { cap: "catalogo_productos", title: "Tu catálogo", hint: "Lo que vendes: productos, precios y existencias." },
  { cap: "agenda", title: "Tu agenda y citas", hint: "Disponibilidad y citas de tu calendario." },
  { cap: "prospeccion", title: "Encuentra clientes nuevos", hint: "Directorios para prospectar." },
  { cap: "compras", title: "Compras y proveedores", hint: "Órdenes de compra y abasto." },
  { cap: "avisos_equipo", title: "Avisos a tu equipo", hint: "Notificaciones internas para tu gente." },
];

function Logo({ node }: { node: IntegrationNode }) {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-line bg-surface">
      {node.logo ? (
        <img
          src={node.logo}
          alt=""
          className="h-5 w-5 object-contain"
          style={{ filter: node.connected ? undefined : "grayscale(1) opacity(0.7)" }}
        />
      ) : (
        <span className="text-[12px] font-bold" style={{ color: node.color }}>
          {node.name.slice(0, 2)}
        </span>
      )}
    </span>
  );
}

function ConnectorButton({ node, onOpen }: { node: IntegrationNode; onOpen: (n: IntegrationNode) => void }) {
  return (
    <button
      onClick={() => onOpen(node)}
      className="group flex items-center gap-3 rounded-lg border border-line bg-surface px-3.5 py-3 text-left transition-colors hover:border-line-strong"
    >
      <Logo node={node} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium text-ink">{node.name}</p>
        <p className="truncate text-[11.5px] text-ink-3">{node.rol}</p>
      </div>
      {node.verified === "error" ? (
        <span
          title={node.last_error ?? undefined}
          className="flex shrink-0 items-center gap-1.5 text-[11.5px] font-medium text-danger"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-danger" />
          Revisar
        </span>
      ) : node.connected ? (
        <span className="flex shrink-0 items-center gap-1.5 text-[11.5px] font-medium text-ok">
          <span className="h-1.5 w-1.5 rounded-full bg-ok" />
          {node.verified === "ok" ? "Verificado" : "Conectado"}
        </span>
      ) : (
        <span className="shrink-0 text-[11.5px] font-medium text-accent-ink">
          {node.key === "excel" ? "Subir" : "Conectar"}
        </span>
      )}
    </button>
  );
}

export default function IntegracionesPage() {
  // useSearchParams (?vista=…, viene del redirect de /mapa) exige Suspense en Next.
  return (
    <Suspense fallback={<div className="min-w-0" />}>
      <Integraciones />
    </Suspense>
  );
}

/** Semáforo honesto de una conexión a la medida: la última corrida y el último Probar. */
function CustomEstado({ c }: { c: CustomConnector }) {
  // Manda la señal MÁS RECIENTE: si acabas de probarla y funciona, el error de una
  // corrida vieja ya no grita "Revisar" (y al revés). Los ISO comparan bien como texto.
  const testEsMasReciente = Boolean(
    c.last_test_at && (!c.last_sync_at || c.last_test_at > c.last_sync_at),
  );
  const falla = testEsMasReciente ? c.last_test_ok === false : Boolean(c.last_error);
  if (falla) {
    return (
      <span
        title={(testEsMasReciente ? c.last_test_error : c.last_error) || undefined}
        className="flex shrink-0 items-center gap-1.5 text-[11.5px] font-medium text-danger"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-danger" />
        Revisar
      </span>
    );
  }
  if (!c.has_secret && c.auth_type) {
    return <span className="shrink-0 text-[11.5px] font-medium text-warn">Falta tu clave</span>;
  }
  if (c.last_sync_at && !c.last_error) {
    return (
      <span
        title={`Última corrida: ${c.last_sync_at}`}
        className="flex shrink-0 items-center gap-1.5 text-[11.5px] font-medium text-ok"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-ok" />
        Sincronizada · {c.last_count ?? 0}
      </span>
    );
  }
  if (c.last_test_ok) {
    return (
      <span className="flex shrink-0 items-center gap-1.5 text-[11.5px] font-medium text-ok">
        <span className="h-1.5 w-1.5 rounded-full bg-ok" />
        Probada
      </span>
    );
  }
  return <span className="shrink-0 text-[11.5px] text-ink-3">Sin probar</span>;
}

function Integraciones() {
  const router = useRouter();
  const { data, error, loading, refetch } = useApi(() => api.integrations(), []);
  const { data: customData, refetch: refetchCustom } = useApi(() => api.listCustomConnectors(), []);
  const [open, setOpen] = useState<IntegrationNode | null>(null);
  const [crear, setCrear] = useState<string | null>(null);
  const [editar, setEditar] = useState<CustomConnector | null>(null);
  const [probando, setProbando] = useState<string | null>(null);
  const [openNeed, setOpenNeed] = useState<string | null>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const custom = customData ?? [];

  async function quitarCustom(id: string) {
    try {
      await api.deleteCustomConnector(id);
      refetchCustom();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  async function probarCustom(c: CustomConnector) {
    setProbando(c.id);
    try {
      const r = await api.retestCustomConnector(c.id);
      if (r.ok) toast(`${c.name}: funciona · ${r.count} registro${r.count === 1 ? "" : "s"} de muestra`, "info");
      else toast(`${c.name}: ${r.error}`, "error");
      refetchCustom();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setProbando(null);
    }
  }

  async function exportarReceta(c: CustomConnector) {
    try {
      const receta = await api.exportCustomConnector(c.id);
      const blob = new Blob([JSON.stringify(receta, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `receta-${c.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  async function importarReceta(file: File) {
    try {
      const receta = JSON.parse(await file.text()) as Record<string, unknown>;
      const creada = await api.importCustomConnector(receta);
      toast("Receta importada. Agrega tu clave y pruébala.", "info");
      refetchCustom();
      setEditar(creada); // directo a capturar la clave y probar
    } catch (e) {
      toast(e instanceof SyntaxError ? "Ese archivo no es una receta JSON válida." : (e as Error).message, "error");
    }
  }
  const vistaParam = useSearchParams().get("vista");
  const [vista, setVista] = useState<"organigrama" | "conectores" | "todos">(
    // "mapa" es compat de enlaces viejos: el mapa se reemplazó por el organigrama.
    vistaParam === "conectores" ? "conectores" : vistaParam === "todos" ? "todos" : "organigrama",
  );

  const systems = data?.systems ?? [];
  const abrir = (node: IntegrationNode) => {
    if (node.key === "sat") router.push("/sat");
    else setOpen(node);
  };

  return (
    <div className="min-w-0">
      <PageHeader
        title="Integraciones"
        subtitle="Dinos qué quieres lograr y te damos las opciones. Tus fuentes siguen mandando: aiuda actúa encima."
        right={
          data && (
            <span className="text-[12px] text-ink-3">
              <span className="font-medium text-ink">{data.connected_count}</span> conectadas ·{" "}
              {data.available_count} disponibles
            </span>
          )
        }
      />

      <Tabs
        tabs={[
          { key: "organigrama", label: "Organigrama" },
          { key: "conectores", label: "Por necesidad" },
          { key: "todos", label: "Todos", count: systems.length || undefined },
        ]}
        active={vista}
        onChange={(k) => setVista(k as typeof vista)}
      />

      {vista !== "organigrama" && (
        <section className="mt-4 overflow-hidden rounded-lg border border-line bg-surface">
          <div className="flex items-center gap-3 border-b border-line bg-panel/30 px-4 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="text-[12px] font-semibold text-ink">Tus conexiones a la medida</p>
              <p className="text-[11px] text-ink-3">
                Fuentes que tú creaste por API. El motor las lee en cada corrida, con su procedencia.
              </p>
            </div>
            <input
              ref={importRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importarReceta(f);
                e.target.value = ""; // permite re-importar el mismo archivo
              }}
            />
            <button
              onClick={() => importRef.current?.click()}
              title="Crea una conexión desde una receta compartida (JSON sin secretos)"
              className="shrink-0 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[11.5px] font-medium text-ink-2 transition-colors hover:border-line-strong"
            >
              Importar receta
            </button>
          </div>
          {custom.length === 0 ? (
            <p className="px-4 py-3 text-[12px] text-ink-3">
              Aún no tienes ninguna. Créala desde una necesidad (&ldquo;¿No está el tuyo?&rdquo;) o
              importa una receta.
            </p>
          ) : (
            <ul>
              {custom.map((c) => (
                <li
                  key={c.id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5 text-[12px] last:border-b-0"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-ink">
                      {c.name}
                      <span className="ml-2 font-normal text-ink-3">
                        {CAP_LABEL[c.cap] ?? c.cap}
                      </span>
                      {/* La receta declara write_path: también recibe altas de aiuda. */}
                      {c.write_path && (
                        <span
                          title="Esta conexión también recibe altas de aiuda (endpoint de escritura declarado)"
                          className="ml-2 rounded bg-panel px-1.5 py-px text-[10.5px] font-medium text-ink-2"
                        >
                          escribe
                        </span>
                      )}
                    </p>
                    <p className="truncate text-[11px] text-ink-3">{c.base_url}</p>
                  </div>
                  <CustomEstado c={c} />
                  <div className="flex shrink-0 items-center gap-2.5">
                    <button
                      onClick={() => probarCustom(c)}
                      disabled={probando === c.id}
                      className="text-[11.5px] font-medium text-accent-ink transition-colors hover:opacity-70 disabled:opacity-50"
                    >
                      {probando === c.id ? "Probando…" : "Probar"}
                    </button>
                    <button
                      onClick={() => setEditar(c)}
                      className="text-[11.5px] font-medium text-accent-ink transition-colors hover:opacity-70"
                    >
                      Editar
                    </button>
                    <button
                      onClick={() => exportarReceta(c)}
                      title="Descarga la receta (JSON sin secretos) para compartirla"
                      className="text-[11.5px] text-ink-3 transition-colors hover:text-ink"
                    >
                      Receta
                    </button>
                    <button
                      onClick={() => quitarCustom(c.id)}
                      className="text-[11.5px] text-ink-3 transition-colors hover:text-danger"
                    >
                      Quitar
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {vista === "organigrama" && (
        <Organigrama
          systems={systems}
          businessName={data?.business_name ?? ""}
          onConnect={abrir}
          // Las fuentes del negocio son las del catálogo YA conectadas más las que
          // creó a la medida: con cero, conectar una es el primer paso real.
          fuentesConectadas={(data?.connected_count ?? 0) + custom.length}
          // La tarjeta "Conecta una fuente" del árbol lleva a la lista completa de
          // conectores de ESTA misma pantalla (cambio de pestaña, sin recargar).
          onVerFuentes={() => setVista("todos")}
        />
      )}

      {vista === "todos" && (
        <div className="reveal-stagger mt-4">
          {error && <ErrorState message={error} retry={refetch} />}
          {loading && !data && (
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-[58px] w-full rounded-lg" />
              ))}
            </div>
          )}
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {systems.map((node) => (
              <ConnectorButton key={node.key} node={node} onOpen={abrir} />
            ))}
          </div>
          {systems.length > 0 && (
            <button
              onClick={() => setCrear("")}
              className="mt-2.5 flex w-full items-center gap-2 rounded-lg border border-dashed border-line-strong bg-surface px-3.5 py-2.5 text-left text-[12px] transition-colors hover:border-accent"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded border border-dashed border-line-strong text-[15px] text-ink-3">
                +
              </span>
              <span className="font-medium text-ink">¿No está el tuyo?</span>
              <span className="hidden text-ink-3 sm:inline">Crea una conexión a la medida.</span>
              <span className="ml-auto shrink-0 font-medium text-accent-ink">Créalo →</span>
            </button>
          )}
        </div>
      )}

      {vista === "conectores" && (
        <>
          {error && <ErrorState message={error} retry={refetch} />}

      {loading && !data && (
        <div className="space-y-2.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-[58px] w-full rounded-lg" />
          ))}
        </div>
      )}

      <div className="reveal-stagger mt-4 space-y-2.5">
        {NEEDS.map((need) => {
          const opts = systems.filter((s) => s.provides.some((p) => p.cap === need.cap));
          if (opts.length === 0) return null;
          const conectadas = opts.filter((s) => s.connected).length;
          const abierto = openNeed === need.cap;
          return (
            <section key={need.cap} className="overflow-hidden rounded-lg border border-line bg-surface">
              <button
                onClick={() => setOpenNeed(abierto ? null : need.cap)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-panel/40"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold text-ink">{need.title}</p>
                  <p className="text-[11.5px] text-ink-3">{need.hint}</p>
                </div>
                {conectadas > 0 ? (
                  <span className="shrink-0 text-[11.5px] font-medium text-ok">
                    {conectadas} conectada{conectadas > 1 ? "s" : ""}
                  </span>
                ) : (
                  <span className="shrink-0 text-[11.5px] text-ink-3">
                    {opts.length} {opts.length > 1 ? "opciones" : "opción"}
                  </span>
                )}
                <svg
                  viewBox="0 0 12 12"
                  className={`h-3 w-3 shrink-0 text-ink-3 transition-transform ${abierto ? "rotate-90" : ""}`}
                  fill="none"
                >
                  <path
                    d="M4.5 3 8 6l-3.5 3"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
              {abierto && (
                <div className="border-t border-line bg-panel/20 px-3 py-3">
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    {opts.map((node) => (
                      <ConnectorButton key={node.key} node={node} onOpen={abrir} />
                    ))}
                  </div>
                  {/* Fallback abierto: si no está tu fuente, la creas a la medida por API. */}
                  <button
                    onClick={() => setCrear(need.cap)}
                    className="mt-2.5 flex w-full items-center gap-2 rounded-lg border border-dashed border-line-strong bg-surface px-3.5 py-2.5 text-left text-[12px] transition-colors hover:border-accent"
                  >
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded border border-dashed border-line-strong text-[15px] text-ink-3">
                      +
                    </span>
                    <span className="font-medium text-ink">¿No está el tuyo?</span>
                    <span className="hidden text-ink-3 sm:inline">Crea una conexión a la medida.</span>
                    <span className="ml-auto shrink-0 font-medium text-accent-ink">Créalo →</span>
                  </button>
                </div>
              )}
            </section>
          );
        })}
        {!loading && !error && systems.length === 0 && (
          <div className="rounded-lg border border-line bg-surface px-6 py-12 text-center text-[13px] text-ink-3">
            No hay integraciones para mostrar.
          </div>
        )}
      </div>
        </>
      )}

      <IntegrationConfigDrawer node={open} onClose={() => setOpen(null)} onSaved={refetch} />
      <CustomConnectorDrawer
        open={crear !== null || editar !== null}
        cap={crear ?? ""}
        editar={editar}
        onClose={() => {
          setCrear(null);
          setEditar(null);
        }}
        onSaved={refetchCustom}
      />
    </div>
  );
}
