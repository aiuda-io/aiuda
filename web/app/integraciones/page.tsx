"use client";

import { Suspense, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, type CustomConnector, type IntegrationNode } from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  SecondaryButton,
  Skeleton,
  Tabs,
  useApi,
} from "@/components/ui";
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
    <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-line bg-surface">
      {node.logo ? (
        <img
          src={node.logo}
          alt=""
          className="h-6 w-6 object-contain"
          style={{ filter: node.connected ? undefined : "grayscale(1) opacity(0.7)" }}
        />
      ) : (
        <span className="text-rotulo font-bold" style={{ color: node.color }}>
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
      className="group flex items-center gap-3.5 rounded-lg border border-line bg-surface px-4 py-3.5 text-left transition-colors hover:border-line-strong"
    >
      <Logo node={node} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-cuerpo font-semibold text-ink">{node.name}</p>
        <p className="truncate text-apoyo text-ink-3">{node.rol}</p>
      </div>
      {node.verified === "error" ? (
        <span
          title={node.last_error ?? undefined}
          className="flex shrink-0 items-center gap-1.5 text-apoyo font-medium text-danger"
        >
          <span className="h-2 w-2 rounded-full bg-danger" />
          Revisar
        </span>
      ) : node.connected ? (
        <span className="flex shrink-0 items-center gap-1.5 text-apoyo font-medium text-ok">
          <span className="h-2 w-2 rounded-full bg-ok" />
          {node.verified === "ok" ? "Verificado" : "Conectado"}
        </span>
      ) : (
        <span className="shrink-0 rounded-md bg-accent-soft px-2.5 py-1 text-apoyo font-semibold text-accent-ink">
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
        className="flex shrink-0 items-center gap-1.5 text-apoyo font-medium text-danger"
      >
        <span className="h-2 w-2 rounded-full bg-danger" />
        Revisar
      </span>
    );
  }
  if (!c.has_secret && c.auth_type) {
    return <span className="shrink-0 text-apoyo font-medium text-warn">Falta tu clave</span>;
  }
  if (c.last_sync_at && !c.last_error) {
    return (
      <span
        title={`Última corrida: ${c.last_sync_at}`}
        className="flex shrink-0 items-center gap-1.5 text-apoyo font-medium text-ok"
      >
        <span className="h-2 w-2 rounded-full bg-ok" />
        Sincronizada · {c.last_count ?? 0}
      </span>
    );
  }
  if (c.last_test_ok) {
    return (
      <span className="flex shrink-0 items-center gap-1.5 text-apoyo font-medium text-ok">
        <span className="h-2 w-2 rounded-full bg-ok" />
        Probada
      </span>
    );
  }
  return <span className="shrink-0 text-apoyo text-ink-3">Sin probar</span>;
}

/** La salida de escape: tu sistema no está en el catálogo y lo conectas por su API. */
function NoEstaElTuyo({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="mt-2.5 flex w-full items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface px-4 py-3.5 text-left text-cuerpo transition-colors hover:border-accent"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-dashed border-line-strong text-seccion text-ink-3">
        +
      </span>
      <span className="font-semibold text-ink">¿No está el tuyo?</span>
      <span className="hidden text-ink-2 sm:inline">
        Crea una conexión a la medida contra tu propia API.
      </span>
      <span className="ml-auto shrink-0 font-semibold text-accent-ink">Créalo</span>
    </button>
  );
}

/** Las conexiones que el dueño creó por API. Al FINAL de la pantalla: es la
 *  salida de escape, no lo primero que hay que leer. Cuando no hay ninguna se
 *  queda en un renglón que dice qué hacer, no en un cajón vacío. */
function ALaMedida({
  custom,
  probando,
  onImportar,
  onCrear,
  onProbar,
  onEditar,
  onReceta,
  onQuitar,
}: {
  custom: CustomConnector[];
  probando: string | null;
  onImportar: () => void;
  onCrear: () => void;
  onProbar: (c: CustomConnector) => void;
  onEditar: (c: CustomConnector) => void;
  onReceta: (c: CustomConnector) => void;
  onQuitar: (id: string) => void;
}) {
  return (
    <section className="mt-9 border-t border-line pt-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-5 gap-y-2">
        <div className="min-w-0">
          <h2 className="text-seccion font-semibold text-ink">Tus conexiones a la medida</h2>
          <p className="text-cuerpo text-ink-2">
            Fuentes que tú creaste por API. El motor las lee en cada corrida, con su procedencia.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <SecondaryButton onClick={onCrear}>Crear una conexión</SecondaryButton>
          <SecondaryButton
            onClick={onImportar}
            title="Crea una conexión desde una receta compartida (JSON sin secretos)"
          >
            Importar receta
          </SecondaryButton>
        </div>
      </div>

      {custom.length === 0 ? (
        <p className="mt-3 text-cuerpo text-ink-3">
          Todavía no tienes ninguna, y está bien: solo las necesitas si tu sistema no aparece
          arriba.
        </p>
      ) : (
        <ul className="mt-3 overflow-hidden rounded-lg border border-line bg-surface">
          {custom.map((c) => (
            <li
              key={c.id}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3 last:border-b-0"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-cuerpo font-semibold text-ink">
                  {c.name}
                  <span className="ml-2 font-normal text-ink-3">{CAP_LABEL[c.cap] ?? c.cap}</span>
                  {/* La receta declara write_path: también recibe altas de aiuda. */}
                  {c.write_path && (
                    <span
                      title="Esta conexión también recibe altas de aiuda (endpoint de escritura declarado)"
                      className="ml-2 rounded bg-panel px-1.5 py-0.5 text-sello font-medium text-ink-2"
                    >
                      escribe
                    </span>
                  )}
                </p>
                <p className="truncate text-apoyo text-ink-3">{c.base_url}</p>
              </div>
              <CustomEstado c={c} />
              <div className="flex shrink-0 items-center gap-4">
                <button
                  onClick={() => onProbar(c)}
                  disabled={probando === c.id}
                  className="text-apoyo font-medium text-accent-ink transition-colors hover:underline disabled:opacity-50"
                >
                  {probando === c.id ? "Probando…" : "Probar"}
                </button>
                <button
                  onClick={() => onEditar(c)}
                  className="text-apoyo font-medium text-accent-ink transition-colors hover:underline"
                >
                  Editar
                </button>
                <button
                  onClick={() => onReceta(c)}
                  title="Descarga la receta (JSON sin secretos) para compartirla"
                  className="text-apoyo text-ink-3 transition-colors hover:text-ink"
                >
                  Receta
                </button>
                <button
                  onClick={() => onQuitar(c.id)}
                  className="text-apoyo text-ink-3 transition-colors hover:text-danger"
                >
                  Quitar
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Integraciones() {
  const router = useRouter();
  const { data, error, loading, refetch } = useApi(() => api.integrations(), []);
  const { data: customData, refetch: refetchCustom } = useApi(() => api.listCustomConnectors(), []);
  const [open, setOpen] = useState<IntegrationNode | null>(null);
  const [crear, setCrear] = useState<string | null>(null);
  const [editar, setEditar] = useState<CustomConnector | null>(null);
  const [probando, setProbando] = useState<string | null>(null);
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
  // Se abre en "Por necesidad" y no en el organigrama. Quien entra aquí viene a
  // conectar algo, y el organigrama de alguien que todavía no tiene ayudantes es
  // una caja vacía que no lo deja ni empezar. "mapa" es compat de enlaces
  // viejos: el mapa se reemplazó por el organigrama.
  const [vista, setVista] = useState<"organigrama" | "conectores" | "todos">(
    vistaParam === "organigrama" ? "organigrama" : vistaParam === "todos" ? "todos" : "conectores",
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
            <span className="text-cuerpo text-ink-2">
              <span className="font-semibold text-ink">{data.connected_count}</span> conectadas ·{" "}
              {data.available_count} disponibles
            </span>
          )
        }
      />

      <Tabs
        tabs={[
          { key: "conectores", label: "Qué quieres conectar" },
          { key: "todos", label: "Todas", count: systems.length || undefined },
          { key: "organigrama", label: "Organigrama" },
        ]}
        active={vista}
        onChange={(k) => setVista(k as typeof vista)}
      />

      {/* Las conexiones a la medida viven ABAJO, no arriba: son la salida de
          escape para quien no encontró su sistema, no lo primero que hay que
          leer. Antes se comían el encabezado de la pantalla con un cajón vacío. */}
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
        <div className="reveal-stagger mt-1">
          {error && <ErrorState message={error} retry={refetch} />}
          {loading && !data && (
            <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 2xl:grid-cols-3">
              {Array.from({ length: 9 }).map((_, i) => (
                <Skeleton key={i} className="h-[70px] w-full rounded-lg" />
              ))}
            </div>
          )}
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 2xl:grid-cols-3">
            {systems.map((node) => (
              <ConnectorButton key={node.key} node={node} onOpen={abrir} />
            ))}
          </div>
          {systems.length > 0 && <NoEstaElTuyo onClick={() => setCrear("")} />}
        </div>
      )}

      {vista === "conectores" && (
        <>
          {error && <ErrorState message={error} retry={refetch} />}

          {loading && !data && (
            <div className="space-y-8">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i}>
                  <Skeleton className="h-6 w-64 rounded" />
                  <div className="mt-3 grid grid-cols-1 gap-2.5 md:grid-cols-2 2xl:grid-cols-3">
                    <Skeleton className="h-[70px] w-full rounded-lg" />
                    <Skeleton className="h-[70px] w-full rounded-lg" />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Nada plegado. Antes eran diez renglones casi idénticos y lo que el
              dueño venía a hacer (conectar el SAT) estaba escondido tras un
              clic; ahora lee el encabezado y ahí mismo está su opción. */}
          <div className="reveal-stagger space-y-7">
            {NEEDS.map((need) => {
              const opts = systems.filter((s) => s.provides.some((p) => p.cap === need.cap));
              if (opts.length === 0) return null;
              const conectadas = opts.filter((s) => s.connected).length;
              return (
                <section key={need.cap}>
                  <div className="flex flex-wrap items-baseline justify-between gap-x-5 gap-y-1">
                    <div className="min-w-0">
                      <h2 className="text-seccion font-semibold text-ink">{need.title}</h2>
                      <p className="text-cuerpo text-ink-2">{need.hint}</p>
                    </div>
                    <div className="flex shrink-0 items-baseline gap-5">
                      {conectadas > 0 ? (
                        <span className="flex items-center gap-2 text-apoyo font-medium text-ok">
                          <span className="h-2 w-2 rounded-full bg-ok" />
                          {conectadas} conectada{conectadas > 1 ? "s" : ""}
                        </span>
                      ) : (
                        <span className="text-apoyo text-ink-3">Sin conectar</span>
                      )}
                      {/* Solo donde el builder de verdad sirve: es el conjunto de
                          necesidades con mapeo de campos (CAP_LABEL). Ofrecerlo en
                          "habla con tus clientes" sería mentir: una receta GET no
                          reemplaza a WhatsApp. */}
                      {need.cap in CAP_LABEL && (
                        <button
                          onClick={() => setCrear(need.cap)}
                          title="Crea una conexión a la medida contra tu propia API"
                          className="text-apoyo font-medium text-accent-ink transition-colors hover:underline"
                        >
                          ¿No está el tuyo?
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-1 gap-2.5 md:grid-cols-2 2xl:grid-cols-3">
                    {opts.map((node) => (
                      <ConnectorButton key={node.key} node={node} onOpen={abrir} />
                    ))}
                  </div>
                </section>
              );
            })}
            {!loading && !error && systems.length === 0 && (
              <EmptyState
                title="No pudimos leer el catálogo de conectores"
                action={<SecondaryButton onClick={refetch}>Volver a intentar</SecondaryButton>}
              >
                Vuelve a cargar la pantalla. Si sigue vacía, revisa que aiuda esté corriendo en
                esta computadora.
              </EmptyState>
            )}
          </div>
        </>
      )}

      {vista !== "organigrama" && (
        <ALaMedida
          custom={custom}
          probando={probando}
          onImportar={() => importRef.current?.click()}
          onCrear={() => setCrear("")}
          onProbar={probarCustom}
          onEditar={setEditar}
          onReceta={exportarReceta}
          onQuitar={quitarCustom}
        />
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
