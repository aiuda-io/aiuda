"use client";

// Pestaña Facturas de Cartera. La lista es para LEER: cada renglón es un solo botón
// que abre el panel de la factura, y ahí viven las acciones (recordar, registrar el
// pago). Antes cada renglón traía sus propios botones y la página juntaba más de cien.

import { useMemo, useState } from "react";
import { api, BUCKET_META, type InvoiceItem } from "@/lib/api";
import { fechaDM } from "@/lib/format";
import {
  EmptyState,
  ErrorState,
  PrimaryLink,
  SearchInput,
  SecondaryButton,
  Skeleton,
  useApi,
  Estado,
  QuietButton,
} from "@/components/ui";
import { InvoiceDrawer } from "@/components/invoice-drawer";
import { AgregarSheet } from "@/components/agregar-sheet";
import { ExportButton } from "@/components/export-button";
import { toast } from "@/components/toast";
import { Filtro } from "@/components/cartera-partes";
import {
  atraso,
  dinero,
  leerFallo,
  nombreMoneda,
  plural,
  RUTA,
  totalesPorMoneda,
  TRAMO_MARCA,
} from "@/lib/cartera";

type Estado = "open" | "paid";
type SortKey = "customer" | "folio" | "amount" | "days_overdue";

// El orden de los tramos de cartera. La etiqueta vive en BUCKET_META (lib/api).
const TRAMOS = ["por_vencer", "vence_pronto", "vencida_reciente", "vencida", "critica"];

/** Cuántos renglones se pintan de entrada. El resto entra con "Ver más". */
const PAGINA = 20;

// Una sola rejilla para encabezado y renglones: cliente, folio, monto, estado.
const COLUMNAS = "md:grid-cols-[minmax(0,1fr)_9rem_10rem_15rem]";

export function CarteraFacturas({ onChanged }: { onChanged?: () => void }) {
  const [estado, setEstado] = useState<Estado>("open");
  const { data, error, loading, refetch, refetchQuiet } = useApi<InvoiceItem[]>(
    () => api.invoices(estado),
    [estado],
  );
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "days_overdue", dir: -1 });
  const [query, setQuery] = useState("");
  const [tramo, setTramo] = useState<string | null>(null);
  const [visibles, setVisibles] = useState(PAGINA);
  const [openId, setOpenId] = useState<string | null>(null);
  const [agregar, setAgregar] = useState(false);
  const [actualizando, setActualizando] = useState(false);

  const todas = useMemo(() => data ?? [], [data]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = todas.filter(
      (inv) =>
        (!tramo || inv.bucket === tramo) &&
        (!q || inv.customer?.toLowerCase().includes(q) || inv.folio?.toLowerCase().includes(q)),
    );
    list.sort((a, b) => {
      const va = a[sort.key];
      const vb = b[sort.key];
      const cmp = typeof va === "number" ? va - (vb as number) : String(va).localeCompare(String(vb));
      return cmp * sort.dir;
    });
    return list;
  }, [todas, sort, query, tramo]);

  const cambio = () => {
    refetchQuiet();
    onChanged?.();
  };

  const actualizar = async () => {
    setActualizando(true);
    try {
      const r = await api.sync();
      if (r.fuentes.length === 0) {
        toast("No tienes ningún sistema conectado del que traer facturas.", "info");
      } else {
        const partes = [
          plural(r.pedidos_importados, "factura nueva", "facturas nuevas"),
          plural(r.pagos_confirmados.length, "pago encontrado", "pagos encontrados"),
        ];
        // El detalle de lo que no respondió viene en crudo del conector: aquí solo se
        // dice que pasó y dónde se revisa.
        const aviso = r.avisos?.length ? " Una conexión no respondió: revísala en Ajustes." : "";
        toast(`Cartera al día: ${partes.join(" y ")}.${aviso}`, r.avisos?.length ? "info" : "success");
      }
      cambio();
    } catch (e) {
      toast(leerFallo(e).mensaje, "error");
    } finally {
      setActualizando(false);
    }
  };

  if (error) return <ErrorState message={error} retry={refetch} />;

  const cargando = loading && !data;
  const vacia = !cargando && todas.length === 0;

  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: 1 }));

  return (
    <div className="min-w-0">
      <AgregarSheet
        open={agregar}
        onClose={() => setAgregar(false)}
        tipo="facturas"
        label="factura"
        onCreated={cambio}
      />

      {cargando ? (
        <Skeleton className="mb-10 h-40 w-full rounded-2xl" />
      ) : (
        !vacia && (
          <Resumen
            facturas={todas}
            estado={estado}
            tramo={tramo}
            onTramo={(t) => {
              setTramo(t);
              setVisibles(PAGINA);
            }}
          />
        )
      )}

      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-3">
        <Filtro
          label="Qué facturas ver"
          activo={estado}
          onChange={(k) => {
            setEstado(k);
            setTramo(null);
            setVisibles(PAGINA);
          }}
          opciones={[
            { key: "open", label: "Por cobrar" },
            { key: "paid", label: "Pagadas" },
          ]}
        />
        {!vacia && (
          <SearchInput
            value={query}
            onChange={(v) => {
              setQuery(v);
              setVisibles(PAGINA);
            }}
            placeholder="Buscar cliente o folio"
          />
        )}
        <div className="barra md:ml-auto">
          <QuietButton onClick={actualizar} disabled={actualizando}>
            {actualizando ? "Actualizando…" : "Actualizar"}
          </QuietButton>
          <ExportButton
            entidad="facturas"
            filtros={{ status: estado, bucket: tramo, q: query }}
            count={rows.length}
          />
          <SecondaryButton onClick={() => setAgregar(true)}>Agregar factura</SecondaryButton>
        </div>
      </div>

      {cargando ? (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-11 w-full" />
          ))}
        </div>
      ) : vacia ? (
        estado === "open" ? (
          <EmptyState
            title="Todavía no hay facturas por cobrar"
            action={<PrimaryLink href={RUTA.importar}>Importar Excel</PrimaryLink>}
          >
            Sube el Excel donde llevas lo que te deben y aquí verás quién te debe, cuánto y
            desde cuándo.
          </EmptyState>
        ) : (
          <EmptyState title="Aún no hay facturas pagadas">
            Cuando registres un pago, la factura sale de Por cobrar y se queda aquí.
          </EmptyState>
        )
      ) : rows.length === 0 ? (
        <EmptyState
          title="Nada coincide"
          action={
            <SecondaryButton
              onClick={() => {
                setQuery("");
                setTramo(null);
              }}
            >
              Ver todas
            </SecondaryButton>
          }
        >
          Ninguna factura coincide con lo que buscas.
        </EmptyState>
      ) : (
        <>
          <div
            className={`hidden gap-x-6 border-b border-line px-3 pb-2.5 text-rotulo font-medium text-ink-3 md:grid ${COLUMNAS}`}
          >
            <Encabezado label="Cliente" k="customer" sort={sort} onSort={toggleSort} />
            <Encabezado label="Folio" k="folio" sort={sort} onSort={toggleSort} />
            <Encabezado label="Monto" k="amount" sort={sort} onSort={toggleSort} right />
            <Encabezado
              label={estado === "open" ? "Estado" : "Pagada"}
              k="days_overdue"
              sort={sort}
              onSort={toggleSort}
            />
          </div>
          <ul>
            {rows.slice(0, visibles).map((inv) => (
              <li key={inv.id} className="border-b border-line last:border-0">
                <Renglon inv={inv} onOpen={() => setOpenId(inv.id)} />
              </li>
            ))}
          </ul>
          {rows.length > visibles && (
            <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2">
              <SecondaryButton onClick={() => setVisibles((n) => n + PAGINA)}>
                Ver {Math.min(PAGINA, rows.length - visibles)} más
              </SecondaryButton>
              <span className="tnum text-apoyo text-ink-3">
                {visibles} de {rows.length}
              </span>
            </div>
          )}
        </>
      )}

      <InvoiceDrawer invoiceId={openId} onClose={() => setOpenId(null)} onChanged={cambio} />
    </div>
  );
}

function Encabezado({
  label,
  k,
  sort,
  onSort,
  right,
}: {
  label: string;
  k: SortKey;
  sort: { key: SortKey; dir: 1 | -1 };
  onSort: (k: SortKey) => void;
  right?: boolean;
}) {
  const on = sort.key === k;
  return (
    <span className={right ? "text-right" : ""}>
      <button
        onClick={() => onSort(k)}
        aria-label={`Ordenar por ${label.toLowerCase()}`}
        className="inline-flex items-center gap-1 hover:text-ink"
      >
        {label}
        {on && (
          <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" aria-hidden="true">
            <path
              d={sort.dir === 1 ? "m3 7.5 3-3 3 3" : "m3 4.5 3 3 3-3"}
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </button>
    </span>
  );
}

/** Un renglón callado: cliente en una línea, folio, monto, y estado con su atraso en
 *  una sola celda. Todo el renglón es UN botón que abre el panel. En teléfono se dobla
 *  en dos líneas (cliente y monto arriba; folio y estado abajo), sin scroll lateral. */
function Renglon({ inv, onOpen }: { inv: InvoiceItem; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className={`grid w-full grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-6 gap-y-1 py-3.5 text-left transition-colors duration-150 hover:bg-panel md:items-center md:rounded-lg md:px-3 ${COLUMNAS}`}
    >
      <span className="order-1 text-cuerpo font-medium text-ink md:truncate" title={inv.customer}>
        {inv.customer}
      </span>
      <span className="tnum order-2 whitespace-nowrap text-right text-cuerpo font-semibold text-ink md:order-3">
        {dinero(inv.amount, inv.currency)}
      </span>
      <span className="order-3 col-span-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 md:contents">
        <span className="tnum truncate text-apoyo text-ink-3 md:order-2">{inv.folio}</span>
        <span className="min-w-0 md:order-4">
          <EstadoFactura inv={inv} />
        </span>
      </span>
    </button>
  );
}

/** Estado y atraso, juntos: un punto con el color del tramo y la frase que lo dice. */
export function EstadoFactura({ inv }: { inv: InvoiceItem }) {
  if (inv.status === "paid") {
    return (
      <Estado tono="ok">
        Pagada{inv.paid_at ? ` el ${fechaDM(inv.paid_at)}` : ""}
      </Estado>
    );
  }
  if (inv.status === "cancelled") {
    return <Estado>Cancelada</Estado>;
  }
  if (inv.payment_reported) {
    return (
      <span
        title="El cliente dice que ya pagó. La factura sigue abierta hasta que tú lo confirmes."
        className="mark"
        style={{ "--mark": "var(--color-warn)" } as React.CSSProperties}
      >
        Dice que ya pagó
      </span>
    );
  }
  return (
    <span
      className="mark tnum"
      style={{ "--mark": TRAMO_MARCA[inv.bucket] ?? "var(--color-ink-3)" } as React.CSSProperties}
    >
      {atraso(inv.days_overdue)}
    </span>
  );
}

/** La cifra de la pestaña y, en Por cobrar, la antigüedad hecha filtro. Pesos y
 *  dólares van cada uno con su cifra: nunca se suman. */
function Resumen({
  facturas,
  estado,
  tramo,
  onTramo,
}: {
  facturas: InvoiceItem[];
  estado: Estado;
  tramo: string | null;
  onTramo: (t: string | null) => void;
}) {
  const totales = useMemo(
    () => totalesPorMoneda(facturas, (i) => i.amount, (i) => i.currency),
    [facturas],
  );
  const principal = totales[0];
  const otras = totales.slice(1);

  // Por tramo: total y cuenta de cada moneda.
  const porTramo = useMemo(
    () =>
      TRAMOS.map((t) => ({
        tramo: t,
        totales: totalesPorMoneda(
          facturas.filter((i) => i.bucket === t),
          (i) => i.amount,
          (i) => i.currency,
        ),
      })).filter((t) => t.totales.length > 0),
    [facturas],
  );

  if (!principal) return null;
  const queSon = estado === "open" ? "por cobrar" : "cobrado";
  const enPrincipal = (t: (typeof porTramo)[number]) =>
    t.totales.find((x) => x.moneda === principal.moneda)?.total ?? 0;

  return (
    <div className="reveal mb-10">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="hero-num text-cifra text-ink">{dinero(principal.total, principal.moneda)}</span>
        <span className="text-cuerpo text-ink-2">
          {queSon} en {plural(principal.count, "factura", "facturas")}
          {otras.length > 0 ? ` en ${nombreMoneda(principal.moneda)}` : ""}
        </span>
      </div>
      {otras.map((t) => (
        <p key={t.moneda} className="mt-1.5 text-cuerpo text-ink-2">
          <span className="tnum text-seccion font-semibold text-ink">{dinero(t.total, t.moneda)}</span>{" "}
          {queSon} en {plural(t.count, "factura", "facturas")} en {nombreMoneda(t.moneda)}
        </p>
      ))}

      {estado === "open" && (
        <>
          {/* La barra es solo de la moneda principal: no se reparte un ancho entre dos monedas. */}
          <div className="mt-6 flex h-1.5 w-full gap-[3px]" aria-hidden="true">
            {porTramo
              .filter((t) => enPrincipal(t) > 0)
              .map((t) => (
                <span
                  key={t.tramo}
                  className={`${BUCKET_META[t.tramo].bar} rounded-full transition-opacity ${
                    tramo && tramo !== t.tramo ? "opacity-25" : ""
                  }`}
                  style={{ width: `${Math.max((enPrincipal(t) / (principal.total || 1)) * 100, 2)}%` }}
                />
              ))}
          </div>
          <div className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 xl:grid-cols-5">
            {porTramo.map((t) => {
              const on = tramo === t.tramo;
              const cuenta = t.totales.reduce((a, x) => a + x.count, 0);
              return (
                <button
                  key={t.tramo}
                  onClick={() => onTramo(on ? null : t.tramo)}
                  aria-pressed={on}
                  className={`-m-2 self-start rounded-lg p-2 text-left transition-colors hover:bg-panel ${
                    on ? "bg-fill" : tramo ? "opacity-55 hover:opacity-100" : ""
                  }`}
                >
                  <span
                    className="mark"
                    style={{ "--mark": TRAMO_MARCA[t.tramo] } as React.CSSProperties}
                  >
                    {BUCKET_META[t.tramo].label}
                  </span>
                  {t.totales.map((x) => (
                    <span key={x.moneda} className="tnum mt-1 block text-seccion font-semibold text-ink">
                      {dinero(x.total, x.moneda)}
                    </span>
                  ))}
                  <span className="tnum mt-0.5 block text-apoyo text-ink-3">
                    {plural(cuenta, "factura", "facturas")}
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
