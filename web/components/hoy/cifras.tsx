"use client";

import Link from "next/link";
import { BUCKET_META, mxn, type Cartera } from "@/lib/api";
import { SOURCE_LABEL } from "@/components/ui";
import { AnimatedNumber } from "@/components/motion";
import { etiquetaTramo } from "@/components/hoy/piezas";

/** Los tramos de antigüedad que ya pasaron de su fecha de pago. */
const VENCIDOS = new Set(["vencida_reciente", "vencida", "critica"]);

/** "12 de Odoo", "4 de tu Excel", "2 creadas en aiuda". */
function deFuente(fuente: string): string {
  if (fuente === "excel") return "de tu Excel";
  if (fuente === "aiuda") return "creadas en aiuda";
  return `de ${SOURCE_LABEL[fuente] ?? fuente}`;
}

function Cifra({
  rotulo,
  valor,
  nota,
}: {
  rotulo: string;
  valor: number;
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
      <span className="hero-num block text-titulo text-ink group-hover:text-accent-ink sm:mt-2">
        <AnimatedNumber value={valor} format={mxn} />
      </span>
      <span className="mt-1.5 hidden text-apoyo text-ink-3 sm:block">{nota}</span>
    </Link>
  );
}

/** Lo que sobrevive del Resumen: cuánto hay por cobrar, cuánto ya venció y cuánto se
 *  recuperó este mes, y debajo la barra de antigüedad. Todo lleva a Cartera. */
export function Cifras({ cartera }: { cartera: Cartera }) {
  const vencidos = cartera.aging.filter((l) => VENCIDOS.has(l.bucket));
  const vencido = vencidos.reduce((s, l) => s + l.total, 0);
  const nVencidas = vencidos.reduce((s, l) => s + l.count, 0);
  const tramos = cartera.aging.filter((l) => l.count > 0);
  const fuentes = Object.entries(cartera.by_source ?? {});
  const facturas = (n: number) => `${n} ${n === 1 ? "factura" : "facturas"}`;

  return (
    <section aria-label="Tu cartera">
      <div className="grid grid-cols-1 gap-x-12 sm:grid-cols-3">
        <Cifra rotulo="Por cobrar" valor={cartera.open_total} nota={facturas(cartera.open_count)} />
        <Cifra rotulo="Vencido" valor={vencido} nota={facturas(nVencidas)} />
        <Cifra
          rotulo="Recuperado este mes"
          valor={cartera.recovered_this_month}
          nota="pagado tras un recordatorio"
        />
      </div>

      {tramos.length > 0 && (
        <Link href="/facturas" className="mt-6 block" aria-label="Antigüedad de la cartera, ver en Cartera">
          <div className="flex h-2 w-full gap-px overflow-hidden rounded-full bg-fill">
            {tramos
              .filter((l) => l.total > 0)
              .map((l) => (
                <div
                  key={l.bucket}
                  className={BUCKET_META[l.bucket]?.bar ?? "bg-ink-3"}
                  style={{
                    width: `${Math.max((l.total / (cartera.open_total || 1)) * 100, 2)}%`,
                  }}
                />
              ))}
          </div>
          <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-1.5">
            {tramos.map((l) => (
              <li key={l.bucket} className="flex items-center gap-2 text-apoyo text-ink-2">
                <span
                  className={`h-2 w-2 shrink-0 rounded-[3px] ${BUCKET_META[l.bucket]?.bar ?? "bg-ink-3"}`}
                />
                {etiquetaTramo(l.bucket)}
                <span className="tnum font-medium text-ink">{mxn(l.total)}</span>
              </li>
            ))}
          </ul>
        </Link>
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
