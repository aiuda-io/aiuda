"use client";

import { useMemo, useState } from "react";
import { api, type AppointmentItem } from "@/lib/api";
import { EmptyState, ErrorState, PageHeader, PrimaryButton, PrimaryLink, SearchInput, Skeleton, SOURCE_LABEL, useApi } from "@/components/ui";
import { RailLayout, RailRow, RailSection, RailStat } from "@/components/rail";
import { RecordDrawer } from "@/components/record-drawer";
import { AgregarSheet } from "@/components/agregar-sheet";
import { ExportButton } from "@/components/export-button";

function formatWhen(iso: string | null): string {
  if (!iso) return "Sin fecha";
  const d = new Date(iso);
  return d.toLocaleString("es-MX", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function CitasPage() {
  const { data, error, loading, refetch } = useApi<AppointmentItem[]>(api.appointments);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<AppointmentItem | null>(null);
  const [agregar, setAgregar] = useState(false);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter(
      (a) =>
        !q ||
        a.title.toLowerCase().includes(q) ||
        (a.customer_name ?? "").toLowerCase().includes(q),
    );
  }, [data, query]);

  // Datos extra planos para el drawer: meta puede traer inyectada_en (objeto),
  // que se pinta aparte como liga; aquí solo pasan los valores de texto.
  const metaPlano = useMemo(() => {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(selected?.meta ?? {})) {
      if (k !== "inyectada_en" && typeof v === "string") out[k] = v;
    }
    return out;
  }, [selected]);

  // Resumen de agenda, derivado de las mismas citas (riel de contexto).
  const agenda = useMemo(() => {
    const now = new Date();
    const todayStr = now.toDateString();
    const weekEnd = now.getTime() + 7 * 864e5;
    const upcoming = (data ?? [])
      .filter((a) => a.starts_at && new Date(a.starts_at).getTime() >= now.getTime())
      .sort((a, b) => new Date(a.starts_at!).getTime() - new Date(b.starts_at!).getTime());
    return {
      total: (data ?? []).length,
      hoy: upcoming.filter((a) => new Date(a.starts_at!).toDateString() === todayStr).length,
      semana: upcoming.filter((a) => new Date(a.starts_at!).getTime() <= weekEnd).length,
      proximas: upcoming.slice(0, 5),
    };
  }, [data]);

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Agenda"
        subtitle="Tus citas. De aquí lee tu ayudante de Recepción."
        right={
          agenda.total > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <ExportButton entidad="citas" filtros={{ q: query }} count={rows.length} />
              <PrimaryButton onClick={() => setAgregar(true)}>Agregar cita</PrimaryButton>
            </div>
          ) : undefined
        }
      />
      <AgregarSheet open={agregar} onClose={() => setAgregar(false)} tipo="citas" label="cita" onCreated={refetch} />

      {loading && <Skeleton className="h-40 w-full" />}

      {!loading && agenda.total === 0 && (
        <EmptyState
          title="Tu agenda está vacía"
          action={<PrimaryLink href="/importar">Subir mi agenda</PrimaryLink>}
        >
          Faltan tus citas. Súbelas en un Excel, tal como las llevas: aiuda reconoce el asunto, el
          cliente y la fecha.
        </EmptyState>
      )}

      {agenda.total > 0 && (
        <RailLayout
          rail={
            <>
              <RailSection label="Agenda">
                <RailStat label="En tu agenda" value={String(agenda.total)} strong />
                <RailStat label="Hoy" value={String(agenda.hoy)} />
                <RailStat label="Próximos 7 días" value={String(agenda.semana)} />
              </RailSection>

              {agenda.proximas.length > 0 && (
                <RailSection label="Próximas">
                  {agenda.proximas.map((a) => (
                    <RailRow key={a.id}>
                      <button onClick={() => setSelected(a)} className="min-w-0 text-left">
                        <span className="block truncate text-cuerpo text-ink-2 hover:text-accent-ink">
                          {a.title}
                        </span>
                        <span className="text-apoyo text-ink-3">{formatWhen(a.starts_at)}</span>
                      </button>
                    </RailRow>
                  ))}
                </RailSection>
              )}
            </>
          }
        >
          <div className="mb-5">
            <SearchInput value={query} onChange={setQuery} placeholder="Buscar por asunto o cliente" />
          </div>
          <ul>
            {rows.map((a) => (
              <li
                key={a.id}
                onClick={() => setSelected(a)}
                className="flex cursor-pointer flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line py-3.5 last:border-0"
              >
                {/* Botón real (no solo li onClick): el detalle se abre con teclado. */}
                <button
                  onClick={() => setSelected(a)}
                  className="min-w-0 truncate text-left text-cuerpo font-medium text-ink hover:text-accent-ink"
                >
                  {a.title}
                </button>
                {a.customer_name && (
                  <span className="min-w-0 truncate text-cuerpo text-ink-2">{a.customer_name}</span>
                )}
                <span className="tnum ml-auto shrink-0 text-apoyo text-ink-3">{formatWhen(a.starts_at)}</span>
                {a.notes && <p className="w-full text-apoyo text-ink-3">{a.notes}</p>}
              </li>
            ))}
            {rows.length === 0 && (
              <li className="px-4 py-12 text-center text-cuerpo text-ink-3">
                Ninguna cita coincide con lo que buscas.
              </li>
            )}
          </ul>
        </RailLayout>
      )}

      <RecordDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected?.title ?? ""}
        subtitle={selected ? formatWhen(selected.starts_at) : undefined}
        fields={
          selected
            ? [
                { label: "Cliente", value: selected.customer_name },
                { label: "Teléfono", value: selected.customer_phone },
                { label: "Cuándo", value: formatWhen(selected.starts_at) },
                { label: "Notas", value: selected.notes },
                // Tras inyectarse, la cita queda LIGADA a su copia en el destino
                // (meta.inyectada_en[destino] = ref + url): texto y salto directo.
                ...Object.entries(selected.meta?.inyectada_en ?? {}).map(([destino, liga]) => ({
                  label: `También está en ${SOURCE_LABEL[destino] ?? destino}`,
                  value: liga?.url ? (
                    <a
                      href={liga.url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium text-accent-ink hover:underline"
                    >
                      {liga.ref ? `Abrir ${liga.ref}` : "Abrir"}
                    </a>
                  ) : (
                    (liga?.ref ?? "Creada allá")
                  ),
                })),
              ]
            : []
        }
        meta={metaPlano}
        // Procedencia: Appointment no guarda presence; el source dice de dónde vino
        // (Excel, Google Calendar, una conexión a la medida) y con eso la barra es
        // honesta. Nacida en aiuda no es espejo de nadie: cae al ramal nativo
        // ("Creado en aiuda") en vez de fingir una fuente externa.
        presence={
          selected?.source && selected.source !== "aiuda"
            ? { [selected.source]: {} }
            : undefined
        }
      />
    </div>
  );
}
