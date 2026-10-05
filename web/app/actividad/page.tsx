"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { dinero } from "@/lib/cartera";
import { EmptyState, ErrorState, PageHeader, Skeleton, Tabs, useApi } from "@/components/ui";
import { RenglonEnviado } from "@/components/hoy/enviado";
import { Marca, TextoMensaje } from "@/components/hoy/piezas";
import { TrabajoAyudantes } from "@/components/hoy/trabajo-ayudantes";
import { claseDe, nombreDe, type Mensaje } from "@/components/hoy/tipos";
import { fechaHora } from "@/lib/format";

/** Actividad: el historial detrás de Hoy. No está en el menú; se llega con "Ver todo
 *  lo enviado". Tres vistas: lo que salió, lo que se rechazó y lo que hicieron los
 *  ayudantes cada vez que trabajaron. */
export default function ActividadPage() {
  return (
    <Suspense fallback={null}>
      <Actividad />
    </Suspense>
  );
}

type Vista = "enviado" | "rechazado" | "ayudantes";
const DE_A = 50;

function Actividad() {
  const params = useSearchParams();
  // `?r=<id>` abre un trabajo de ayudante en particular (ligas viejas a esta página).
  const trabajo = params.get("r") ?? "";
  const pedida = params.get("vista");
  const [vista, setVista] = useState<Vista>(
    trabajo ? "ayudantes" : pedida === "rechazado" || pedida === "ayudantes" ? pedida : "enviado",
  );

  const { data, error, loading, refetch } = useApi(async () => {
    const [enviados, rechazados] = await Promise.all([
      api.reminders("sent") as Promise<Mensaje[]>,
      api.reminders("rejected") as Promise<Mensaje[]>,
    ]);
    return {
      enviados: enviados
        .filter((m) => m.sent_at)
        .sort((a, b) => (b.sent_at ?? "").localeCompare(a.sent_at ?? "")),
      rechazados,
    };
  }, []);

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Actividad"
        subtitle="Todo lo que salió a tus clientes, lo que rechazaste y lo que hicieron tus ayudantes."
        right={
          <Link href="/" className="btn btn-secondary">
            Ir a Hoy
          </Link>
        }
      />
      <Tabs
        active={vista}
        onChange={(k) => setVista(k as Vista)}
        tabs={[
          { key: "enviado", label: "Enviado", count: data?.enviados.length },
          { key: "rechazado", label: "Rechazado", count: data?.rechazados.length },
          { key: "ayudantes", label: "Tus ayudantes" },
        ]}
      />
      {vista === "ayudantes" ? (
        <TrabajoAyudantes abrir={trabajo} />
      ) : loading && !data ? (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full rounded-lg" />
          <Skeleton className="h-14 w-full rounded-lg" />
        </div>
      ) : vista === "enviado" ? (
        <Enviados mensajes={data?.enviados ?? []} />
      ) : (
        <Rechazados mensajes={data?.rechazados ?? []} />
      )}
    </div>
  );
}

function Enviados({ mensajes }: { mensajes: Mensaje[] }) {
  const [hasta, setHasta] = useState(DE_A);
  if (mensajes.length === 0) {
    return (
      <EmptyState title="Todavía no sale ningún mensaje">
        Lo que apruebes y se envíe de verdad a tus clientes queda aquí, con su texto.
      </EmptyState>
    );
  }
  return (
    <>
      <ul>
        {mensajes.slice(0, hasta).map((m) => (
          <RenglonEnviado key={m.id} m={m} conFecha />
        ))}
      </ul>
      {mensajes.length > hasta && (
        <button type="button" onClick={() => setHasta(hasta + DE_A)} className="btn btn-secondary mt-4">
          Ver más
        </button>
      )}
    </>
  );
}

function Rechazados({ mensajes }: { mensajes: Mensaje[] }) {
  const [hasta, setHasta] = useState(DE_A);
  if (mensajes.length === 0) {
    return (
      <EmptyState title="No has rechazado nada">
        Los mensajes que rechaces, y los que aiuda retire porque la factura dejó de cobrarse,
        quedan aquí.
      </EmptyState>
    );
  }
  return (
    <>
      <ul>
        {mensajes.slice(0, hasta).map((m) => (
          <Rechazado key={m.id} m={m} />
        ))}
      </ul>
      {mensajes.length > hasta && (
        <button type="button" onClick={() => setHasta(hasta + DE_A)} className="btn btn-secondary mt-4">
          Ver más
        </button>
      )}
    </>
  );
}

function Rechazado({ m }: { m: Mensaje }) {
  const [ver, setVer] = useState(false);
  const [abierto, setAbierto] = useState(true);
  return (
    <li className="border-t border-line py-4 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <span className="text-cuerpo font-semibold text-ink">{nombreDe(m)}</span>
          <span className="ml-2 text-apoyo text-ink-3">
            {claseDe(m)}
            {m.folio ? ` · Factura ${m.folio}` : ""}
          </span>
        </div>
        {m.amount != null && (
          <span className="tnum text-cuerpo font-medium text-ink">{dinero(m.amount, m.currency)}</span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-apoyo text-ink-3">
        <Marca>{m.retirado ? "Retirado" : "Lo rechazaste"}</Marca>
        {m.updated_at && <span>{fechaHora(m.updated_at)}</span>}
        <button
          type="button"
          onClick={() => setVer((v) => !v)}
          aria-expanded={ver}
          className="font-medium text-accent-ink underline-offset-2 hover:underline"
        >
          {ver ? "Ocultar mensaje" : "Ver mensaje"}
        </button>
        {/* Corregir y enviar se hace en Hoy, que es donde están las acciones. */}
        {!m.retirado && (
          <Link
            href={`/?r=${m.id}`}
            className="font-medium text-accent-ink underline-offset-2 hover:underline"
          >
            Corregir en Hoy
          </Link>
        )}
      </div>
      {m.retirado && <p className="mt-2 text-cuerpo text-ink-2">{m.retirado}</p>}
      {ver && (
        <div className="mt-3">
          <TextoMensaje texto={m.message} abierto={abierto} onAbrir={setAbierto} />
        </div>
      )}
    </li>
  );
}
