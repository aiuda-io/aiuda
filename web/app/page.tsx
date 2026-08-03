"use client";

import Link from "next/link";
import {
  api,
  BUCKET_META,
  mxn,
  type AgentState,
  type AiuditasCatalog,
  type AyudanteDTO,
  type Cartera,
  type ReminderItem,
} from "@/lib/api";
import { BucketPill, ErrorState, PageHeader, Skeleton, useApi } from "@/components/ui";
import { AnimatedNumber } from "@/components/motion";
import { Avatar } from "@/components/avatar";
import { normalizeAppearance } from "@/lib/look";
import { useAyudantes, useCatalog } from "@/lib/ayudantes-store";
import { perfilesActivos } from "@/lib/perfiles";

export default function ResumenPage() {
  const cartera = useApi<Cartera>(api.cartera);
  const reminders = useApi<ReminderItem[]>(() => api.reminders());
  const agents = useApi<AgentState[]>(api.agents);
  const { ayudantes } = useAyudantes();
  const { catalog } = useCatalog();

  if (cartera.error) return <ErrorState message={cartera.error} retry={cartera.refetch} />;
  const data = cartera.data;

  const fecha = new Date().toLocaleDateString("es-MX", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  // El equipo son los ayudantes que el DUEÑO creó, no el roster de slugs del motor.
  // Antes esta sección pintaba "Cobranza", un trabajador que él nunca contrató, y su
  // ayudante real solo aparecía en un rincón del sidebar.

  return (
    <div className="min-w-0">
      <PageHeader title="Resumen" subtitle={`${data?.business_name ?? "…"} · ${fecha}`} />

      {data && data.open_count === 0 && data.recovered_this_month === 0 && (
        <FirstRunChecklist
          hasSource={Object.keys(data.by_source ?? {}).length > 0}
          hasAssistant={ayudantes.length > 0}
          hasApproval={(agents.data ?? []).some((a) => a.sent > 0)}
        />
      )}

      {/* Tu equipo: cada agente presume su avance y te lleva a lo suyo */}
      <section
        className="reveal-stagger mb-6 grid grid-cols-1 gap-4 md:grid-cols-2"
      >
        {agents.error ? (
          <p className="rounded-lg border border-line bg-surface px-4 py-3 text-cuerpo text-ink-3 md:col-span-2">
            No pudimos cargar a tu equipo.{" "}
            <button
              onClick={agents.refetch}
              className="font-medium text-accent-ink hover:underline"
            >
              Reintentar
            </button>
          </p>
        ) : agents.loading ? (
          <Skeleton className="h-24 w-full md:col-span-2" />
        ) : ayudantes.length > 0 ? (
          ayudantes.map((a) => <AyudanteCard key={a.id} a={a} catalog={catalog} />)
        ) : (
          <SinEquipo />
        )}
      </section>

      {/* Cifras del mes */}
      <section className="elev-sm grid grid-cols-2 divide-line rounded-lg border border-line bg-surface md:grid-cols-4 md:divide-x">
        <Figure
          label="Recuperado este mes"
          value={data ? data.recovered_this_month : null}
          format={mxn}
          caption="pagos tras recordatorio"
          href="/centro"
        />
        <Figure
          label="Cartera abierta"
          value={data ? data.open_total : null}
          format={mxn}
          caption={data ? `${data.open_count} facturas` : ""}
          href="/facturas"
        />
        <Figure
          label="Promesas activas"
          value={data ? data.active_promises : null}
          caption="propone el siguiente recordatorio"
          href="/promesas"
        />
        <Figure
          label="Pagos por confirmar"
          value={data ? data.payment_reports : null}
          caption="el cliente dice que ya pagó"
          href="/facturas"
          accent={Boolean(data && data.payment_reports > 0)}
        />
      </section>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* Antigüedad */}
        <section className="lg:col-span-3">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-seccion font-semibold text-ink">Antigüedad de cartera</h2>
            <Link href="/facturas" className="text-cuerpo font-medium text-accent-ink hover:underline">
              Ver facturas
            </Link>
          </div>
          <div className="rounded-lg border border-line bg-surface p-4">
            {!data ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <>
                <div className="mb-2.5 flex items-baseline justify-between">
                  <span className="tnum text-seccion font-semibold text-ink">
                    <AnimatedNumber value={data.open_total} format={mxn} />
                  </span>
                  <span className="tnum text-cuerpo text-ink-3">
                    por cobrar · {data.open_count} {data.open_count === 1 ? "factura" : "facturas"}
                  </span>
                </div>
                <div className="flex h-2.5 w-full gap-px overflow-hidden rounded-full bg-line/40">
                  {data.aging
                    .filter((l) => l.total > 0)
                    .map((l) => (
                      <div
                        key={l.bucket}
                        title={`${BUCKET_META[l.bucket].label}: ${mxn(l.total)}`}
                        className={BUCKET_META[l.bucket].bar}
                        style={{
                          width: `${Math.max((l.total / (data.open_total || 1)) * 100, 2)}%`,
                        }}
                      />
                    ))}
                </div>
                <ul className="mt-4">
                  {data.aging
                    .filter((l) => l.count > 0)
                    .map((l) => (
                      <li
                        key={l.bucket}
                        className="flex items-center justify-between border-b border-line/60 py-2 last:border-0"
                      >
                        <span className="flex items-center gap-2 text-cuerpo text-ink-2">
                          <span className={`h-2 w-2 rounded-[3px] ${BUCKET_META[l.bucket].bar}`} />
                          {BUCKET_META[l.bucket].label}
                          <span className="tnum text-apoyo text-ink-3">· {l.count}</span>
                        </span>
                        <span className="tnum text-cuerpo font-medium text-ink">
                          {mxn(l.total)}
                        </span>
                      </li>
                    ))}
                </ul>
                {/* Procedencia: estos números existen por una razón rastreable */}
                <p className="mt-3 border-t border-line/60 pt-2.5 text-apoyo text-ink-3">
                  Fuentes:{" "}
                  {Object.entries(data.by_source)
                    .map(
                      ([source, n]) =>
                        `${n} de ${source === "odoo" ? "Odoo (verificadas)" : source === "excel" ? "tu Excel" : source}`,
                    )
                    .join(" · ")}
                  {data.payment_reports > 0 &&
                    ` · ${data.payment_reports} pago reportado por confirmar`}
                </p>
              </>
            )}
          </div>
        </section>

        {/* Por aprobar */}
        <section className="lg:col-span-2">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-seccion font-semibold text-ink">Esperan tu aprobación</h2>
            <Link
              href="/centro"
              className="text-cuerpo font-medium text-accent-ink hover:underline"
            >
              Revisar todo
            </Link>
          </div>
          <div className="rounded-lg border border-line bg-surface">
            {reminders.loading ? (
              <div className="space-y-2 p-4">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : reminders.error ? (
              // Un error NO es una bandeja limpia: decirlo evita una falsa calma.
              <p className="px-4 py-10 text-center text-cuerpo text-ink-3">
                No pudimos cargar tus aprobaciones.{" "}
                <button
                  onClick={reminders.refetch}
                  className="font-medium text-accent-ink hover:underline"
                >
                  Reintentar
                </button>
              </p>
            ) : (reminders.data ?? []).length === 0 ? (
              <p className="px-4 py-10 text-center text-cuerpo text-ink-3">
                Bandeja limpia. Tu equipo redacta lo siguiente cuando sincronices tus fuentes.
              </p>
            ) : (
              <ul>
                {(reminders.data ?? []).slice(0, 5).map((r) => (
                  <li key={r.id} className="border-b border-line/60 last:border-0">
                    <Link
                      href={`/centro?r=${r.id}`}
                      className="flex items-center gap-2.5 px-4 py-2.5 transition-colors hover:bg-panel/60"
                    >
                      {/* Quién la redactó: el ayudante del dueño, no el slug del motor. */}
                      <span title={r.propuesto_por ? `de ${r.propuesto_por}` : "Tu ayudante"}>
                        <Avatar name={r.propuesto_por ?? ""} size={24} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-cuerpo font-medium text-ink">
                          {r.customer ?? r.title}
                        </p>
                        <p className="tnum truncate text-apoyo text-ink-3">
                          {r.folio && r.amount != null
                            ? `${r.folio} · ${mxn(r.amount)}`
                            : "cotización"}
                        </p>
                      </div>
                      {r.bucket !== "cotizacion" && <BucketPill bucket={r.bucket} />}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function AyudanteCard({ a, catalog }: { a: AyudanteDTO; catalog: AiuditasCatalog | null }) {
  // El oficio se deriva de las aiuditas que tiene activas, igual que en su ficha: es
  // lo que de verdad sabe hacer, no una etiqueta fija.
  const perfiles = catalog ? perfilesActivos(catalog, a.aiuditas) : [];
  const app = normalizeAppearance(a.appearance);
  const detalle = `/ayudantes/detalle?id=${a.id}`;
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="flex items-center gap-3">
        <Link href={detalle} className="shrink-0">
          <Avatar
            name={a.name}
            size={44}
            {...app}
            className="transition-transform hover:scale-105"
          />
        </Link>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Link
              href={detalle}
              className="text-seccion font-semibold text-ink hover:text-accent-ink"
            >
              {a.name}
            </Link>
            {/* Dato neutro de trayectoria: acciones reales, sin nivel ni barra de
                juego (nada de gamificación cerca de montos). */}
            <span className="tnum text-apoyo text-ink-3">
              {a.acciones.total} {a.acciones.total === 1 ? "acción" : "acciones"}
            </span>
          </div>
          <p className="truncate text-cuerpo text-ink-2">
            {perfiles.length > 0
              ? perfiles.map((p) => p.name).join(" · ")
              : "Sin oficio todavía · elige qué quieres que haga"}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {a.acciones.pendientes > 0 && (
          <Quick href="/centro" label={`Bandeja (${a.acciones.pendientes})`} accent />
        )}
        <Quick href={detalle} label="Su trabajo" />
      </div>
    </div>
  );
}

/** Todavía no hay a quién delegarle nada. Un solo camino, no tres. */
function SinEquipo() {
  return (
    <div className="rounded-lg border border-dashed border-line bg-surface px-4 py-5 md:col-span-2">
      <p className="text-cuerpo font-medium text-ink">Todavía no tienes ayudantes</p>
      <p className="mt-0.5 text-cuerpo text-ink-3">
        Un ayudante lee tus fuentes, propone el trabajo y espera tu visto bueno.
      </p>
      <Link
        href="/ayudantes"
        className="mt-3 inline-block rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong"
      >
        Crear el primero
      </Link>
    </div>
  );
}

function Quick({ href, label, accent }: { href: string; label: string; accent?: boolean }) {
  return (
    <Link
      href={href}
      className={`rounded-md px-2 py-1 text-sello font-medium transition-colors ${
        accent
          ? "bg-accent-soft text-accent-ink hover:bg-accent hover:text-surface"
          : "bg-panel text-ink-2 hover:bg-line/60 hover:text-ink"
      }`}
    >
      {label}
    </Link>
  );
}

function Figure({
  label,
  value,
  format = (n) => String(Math.round(n)),
  caption,
  href,
  accent,
}: {
  label: string;
  value: number | null;
  format?: (n: number) => string;
  caption: string;
  href?: string;
  accent?: boolean;
}) {
  const inner = (
    <div className="px-5 py-4">
      <p className="text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">{label}</p>
      {value === null ? (
        <Skeleton className="mt-2 h-7 w-24" />
      ) : (
        <p
          className={`hero-num mt-1.5 text-cifra font-semibold leading-none ${
            accent ? "text-warn" : "text-ink"
          }`}
        >
          <AnimatedNumber value={value} format={format} />
        </p>
      )}
      <p className="mt-2 text-apoyo text-ink-3">{caption}</p>
    </div>
  );
  return href ? (
    <Link href={href} className="block transition-colors hover:bg-panel/50">
      {inner}
    </Link>
  ) : (
    inner
  );
}

function FirstRunChecklist({
  hasSource,
  hasAssistant,
  hasApproval,
}: {
  hasSource: boolean;
  hasAssistant: boolean;
  hasApproval: boolean;
}) {
  const steps = [
    {
      href: "/integraciones",
      n: 1,
      done: hasSource,
      title: "Conecta una fuente",
      desc: "Sube tu Excel o conecta Odoo, WhatsApp y tu banco. La IA entiende tu estructura; no migras nada.",
      cta: "Ir a integraciones",
    },
    {
      href: "/ayudantes",
      n: 2,
      done: hasAssistant,
      title: "Crea tu ayudante",
      desc: "Elige una plantilla o ármalo desde cero. Le pones nombre, cara y sus aiuditas.",
      cta: "Crear ayudante",
    },
    {
      href: "/centro",
      n: 3,
      done: hasApproval,
      title: "Aprueba tu primer trabajo",
      desc: "Tu ayudante redacta y propone; nada sale sin tu visto bueno. Lo apruebas en segundos.",
      cta: "Ver aprobaciones",
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  return (
    <section className="mb-6 overflow-hidden rounded-lg border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-line/60 px-5 py-3.5">
        <div>
          <h2 className="text-seccion font-semibold text-ink">Primeros pasos</h2>
          <p className="mt-0.5 text-cuerpo text-ink-3">
            Tres pasos para poner a trabajar tu primer ayudante.
          </p>
        </div>
        <span className="tnum shrink-0 rounded-full bg-panel px-2.5 py-1 text-sello font-medium text-ink-2">
          {doneCount} de {steps.length}
        </span>
      </div>
      <ol>
        {steps.map((s) => (
          <li key={s.href} className="border-b border-line/60 last:border-0">
            <Link
              href={s.href}
              className="group flex items-center gap-3.5 px-5 py-3.5 transition-colors hover:bg-panel/60"
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-apoyo font-semibold ${
                  s.done
                    ? "bg-ok text-surface"
                    : "border border-line-strong text-ink-3 transition-colors group-hover:border-accent group-hover:text-accent-ink"
                }`}
              >
                {s.done ? (
                  <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none">
                    <path
                      d="m2.5 6.5 2.5 2.5 4.5-5"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                ) : (
                  s.n
                )}
              </span>
              <div className="min-w-0 flex-1">
                <p
                  className={`text-cuerpo font-medium ${
                    s.done ? "text-ink-3 line-through" : "text-ink"
                  }`}
                >
                  {s.title}
                </p>
                <p className="mt-0.5 text-cuerpo text-ink-3">{s.desc}</p>
              </div>
              {!s.done && (
                <span className="hidden shrink-0 items-center gap-1 text-cuerpo font-medium text-accent-ink sm:flex">
                  {s.cta}
                  <svg
                    viewBox="0 0 12 12"
                    className="h-3 w-3 transition-transform group-hover:translate-x-0.5"
                    fill="none"
                  >
                    <path
                      d="m4.5 2.5 3.5 3.5-3.5 3.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
              )}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
