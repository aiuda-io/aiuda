"use client";

import Link from "next/link";
import { BUCKET_META, type Cartera, type CarteraMoneda } from "@/lib/api";
import { SOURCE_LABEL } from "@/components/ui";
import { AnimatedNumber } from "@/components/motion";
import { etiquetaTramo } from "@/components/hoy/piezas";
import { dinero, nombreMoneda, plural } from "@/lib/cartera";

/** Los tramos de antigüedad que ya pasaron de su fecha de pago. */
const VENCIDOS = new Set(["vencida_reciente", "vencida", "critica"]);

/** "12 de Odoo", "4 de tu Excel", "2 creadas en aiuda". */
function deFuente(fuente: string): string {
  if (fuente === "excel") return "de tu Excel";
  if (fuente === "aiuda") return "creadas en aiuda";
  return `de ${SOURCE_LABEL[fuente] ?? fuente}`;
}

const facturas = (n: number) => plural(n, "factura", "facturas");

function vencidoDe(m: CarteraMoneda): { total: number; count: number } {
  const lineas = m.aging.filter((l) => VENCIDOS.has(l.bucket));
  return {
    total: lineas.reduce((s, l) => s + l.total, 0),
    count: lineas.reduce((s, l) => s + l.count, 0),
  };
}

function Cifra({
  rotulo,
  valor,
  moneda,
  nota,
}: {
  rotulo: string;
  valor: number;
  moneda: string;
  nota: string;
}) {
  return (
    // En teléfono cada cifra es un renglón (rótulo a la izquierda, número a la derecha):
    // tres columnas de seis cifras no caben en 390 px.
    <Link
      href="/facturas"
      className="group flex items-baseline justify-between gap-4 py-2 sm:block sm:py-0"
    >
      <span className="min-w-0">
        <span className="eyebrow block">{rotulo}</span>
        <span className="block text-apoyo text-ink-3 sm:hidden">{nota}</span>
      </span>
      <span className="hero-num block whitespace-nowrap text-titulo text-ink group-hover:text-accent-ink sm:mt-2">
        <AnimatedNumber value={valor} format={(v) => dinero(v, moneda)} />
      </span>
      <span className="mt-1.5 hidden text-apoyo text-ink-3 sm:block">{nota}</span>
    </Link>
  );
}

/** Lo que el negocio cobra en OTRA moneda, en un renglón callado. Nunca se suma a la
 *  cifra grande: un dólar no es un peso. */
function OtraMoneda({ m }: { m: CarteraMoneda }) {
  const vencido = vencidoDe(m);
  const partes = [
    m.open_count > 0 && (
      <>
        <span className="tnum font-medium text-ink">{dinero(m.open_total, m.moneda)}</span> por
        cobrar en {facturas(m.open_count)}
      </>
    ),
    vencido.count > 0 && (
      <>
        <span className="tnum font-medium text-ink">{dinero(vencido.total, m.moneda)}</span> vencido
      </>
    ),
    m.recovered_this_month > 0 && (
      <>
        <span className="tnum font-medium text-ink">
          {dinero(m.recovered_this_month, m.moneda)}
        </span>{" "}
        recuperado este mes
      </>
    ),
  ].filter(Boolean);
  if (partes.length === 0) return null;
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-apoyo text-ink-2">
      <span className="text-ink-3">En {nombreMoneda(m.moneda)}:</span>
      {partes.map((parte, i) => (
        <span key={i}>
          {parte}
          {i < partes.length - 1 ? "," : ""}
        </span>
      ))}
    </li>
  );
}

/** Cuánto hay por cobrar, cuánto ya venció y cuánto se recuperó este mes, y debajo la
 *  barra de antigüedad. Todo lleva a Cartera.
 *
 *  Las tres cifras grandes hablan de UNA moneda, la principal del negocio
 *  (`moneda_principal` de /v1/cartera). Si además cobra en otra, va en su propio
 *  renglón: pesos y dólares nunca se suman. */
export function Cifras({ cartera }: { cartera: Cartera }) {
  const principal: CarteraMoneda = cartera.por_moneda?.find(
    (m) => m.moneda === cartera.moneda_principal,
  ) ?? {
    moneda: cartera.moneda_principal ?? "MXN",
    open_total: cartera.open_total,
    open_count: cartera.open_count,
    overdue_total: 0,
    recovered_this_month: cartera.recovered_this_month,
    aging: cartera.aging,
  };
  const otras = (cartera.por_moneda ?? []).filter((m) => m.moneda !== principal.moneda);
  const vencido = vencidoDe(principal);
  const tramos = principal.aging.filter((l) => l.count > 0);
  const fuentes = Object.entries(cartera.by_source ?? {});

  return (
    <section aria-label="Tu cartera">
      <div className="grid grid-cols-1 gap-x-12 sm:grid-cols-3">
        <Cifra
          rotulo="Por cobrar"
          valor={principal.open_total}
          moneda={principal.moneda}
          nota={facturas(principal.open_count)}
        />
        <Cifra
          rotulo="Vencido"
          valor={vencido.total}
          moneda={principal.moneda}
          nota={facturas(vencido.count)}
        />
        <Cifra
          rotulo="Recuperado este mes"
          valor={principal.recovered_this_month}
          moneda={principal.moneda}
          nota="pagado tras un recordatorio"
        />
      </div>

      {tramos.length > 0 && (
        <Link href="/facturas" className="mt-6 block" aria-label="Antigüedad de la cartera, ver en Cartera">
          <div className="flex h-1.5 w-full gap-px overflow-hidden rounded-full bg-fill">
            {tramos
              .filter((l) => l.total > 0)
              .map((l) => (
                <div
                  key={l.bucket}
                  className={BUCKET_META[l.bucket]?.bar ?? "bg-ink-3"}
                  style={{
                    width: `${Math.max((l.total / (principal.open_total || 1)) * 100, 2)}%`,
                  }}
                />
              ))}
          </div>
          <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-1.5">
            {tramos.map((l) => (
              <li key={l.bucket} className="flex items-center gap-2 text-apoyo text-ink-2">
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${BUCKET_META[l.bucket]?.bar ?? "bg-ink-3"}`}
                />
                {etiquetaTramo(l.bucket)}
                <span className="tnum font-medium text-ink">{dinero(l.total, principal.moneda)}</span>
              </li>
            ))}
          </ul>
        </Link>
      )}

      {otras.length > 0 && (
        <ul className="mt-4 space-y-1">
          {otras.map((m) => (
            <OtraMoneda key={m.moneda} m={m} />
          ))}
        </ul>
      )}

      {/* Procedencia: estas cifras existen por una razón rastreable. */}
      {(fuentes.length > 0 || cartera.payment_reports > 0) && (
        <p className="mt-3 text-apoyo text-ink-3">
          {fuentes.length > 0 &&
            `Fuentes: ${fuentes
              .map(([fuente, n]) => `${n} ${deFuente(fuente)}`)
              .join(", ")}.`}
          {cartera.payment_reports > 0 && (
            <>
              {" "}
              <Link
                href="/facturas?vista=pagos"
                className="font-medium text-accent-ink underline-offset-2 hover:underline"
              >
                {cartera.payment_reports === 1
                  ? "1 cliente dice que ya pagó"
                  : `${cartera.payment_reports} clientes dicen que ya pagaron`}
              </Link>
            </>
          )}
        </p>
      )}
    </section>
  );
}
