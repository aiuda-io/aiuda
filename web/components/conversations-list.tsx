"use client";

// La bandeja de Mensajes: WhatsApp y correo en una sola lista, fija a la izquierda
// mientras el hilo se abre a la derecha. Arriba va quien contestó hoy, marcado, para
// que se note de un vistazo sin abrir cliente por cliente.
import { useMemo, useState } from "react";
import Link from "next/link";
import { type ConversationItem, type ConversationStatus } from "@/lib/api";
import { EmptyState, ErrorState, PrimaryLink, SearchInput, Skeleton, Tabs } from "@/components/ui";
import { esDeHoy, haceTiempo } from "@/lib/format";
import { rutaAjustes } from "@/lib/ajustes";

type TabKey = "identificados" | "por_identificar" | "descartados";

const STATUS_TAB: Record<ConversationStatus, TabKey> = {
  identificado: "identificados",
  por_identificar: "por_identificar",
  descartado: "descartados",
};

const TAB_LABEL: Record<TabKey, string> = {
  identificados: "Identificados",
  por_identificar: "Por identificar",
  descartados: "Descartadas",
};

/** ¿El último mensaje es del cliente y llegó hoy (hora de esta computadora)? */
export function contestoHoy(c: ConversationItem): boolean {
  return c.last_direction === "in" && esDeHoy(c.last_at);
}

export function tituloDe(c: ConversationItem): string {
  if (c.customer) return c.customer;
  if (c.channel === "correo") return c.correo?.nombre || c.correo?.de || "Correo sin remitente";
  return c.remote_phone;
}

export function ConversationsList({
  conversations,
  loading,
  error,
  retry,
  activeId,
}: {
  conversations: ConversationItem[];
  loading: boolean;
  error: string | null;
  retry: () => void;
  activeId: string;
}) {
  const [elegida, setElegida] = useState<TabKey | null>(null);
  const [query, setQuery] = useState("");

  const counts = useMemo(() => {
    const c: Record<TabKey, number> = { identificados: 0, por_identificar: 0, descartados: 0 };
    for (const x of conversations) c[STATUS_TAB[x.status]]++;
    return c;
  }, [conversations]);

  // "Identificados" siempre está; las otras dos solo si tienen algo. Si el dueño
  // llega con un hilo abierto, la bandeja se para en la pestaña de ese hilo.
  const visibles = (["identificados", "por_identificar", "descartados"] as TabKey[]).filter(
    (k) => k === "identificados" || counts[k] > 0,
  );
  const delHilo = conversations.find((c) => c.id === activeId);
  const porDefecto: TabKey =
    (delHilo && STATUS_TAB[delHilo.status]) ||
    (counts.identificados > 0 ? "identificados" : (visibles.find((k) => counts[k] > 0) ?? "identificados"));
  const tab = elegida && visibles.includes(elegida) ? elegida : porDefecto;

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return conversations
      .filter((c) => STATUS_TAB[c.status] === tab)
      .filter(
        (c) =>
          !q ||
          (c.customer ?? "").toLowerCase().includes(q) ||
          c.remote_phone.includes(q) ||
          (c.correo?.de ?? "").toLowerCase().includes(q) ||
          (c.correo?.asunto ?? "").toLowerCase().includes(q),
      )
      .sort((a, b) => {
        // Quien contestó hoy va arriba; después, lo más reciente.
        const ha = contestoHoy(a) ? 1 : 0;
        const hb = contestoHoy(b) ? 1 : 0;
        if (ha !== hb) return hb - ha;
        return (b.last_at ?? "").localeCompare(a.last_at ?? "");
      });
  }, [conversations, tab, query]);

  const hoy = useMemo(
    () => conversations.filter((c) => c.status === "identificado" && contestoHoy(c)).length,
    [conversations],
  );

  return (
    <div className="flex h-full min-w-0 flex-col">
      <header className="shrink-0 px-5 pb-4 pt-5">
        <h1 className="text-titulo font-semibold text-ink">Mensajes</h1>
        {!loading && !error && conversations.length > 0 && (
          <p className="mt-1 text-cuerpo text-ink-2">
            {hoy === 0
              ? "Nadie ha contestado hoy."
              : hoy === 1
                ? "1 cliente contestó hoy."
                : `${hoy} clientes contestaron hoy.`}
          </p>
        )}
      </header>

      {error ? (
        <ErrorState message={error} retry={retry} />
      ) : loading ? (
        <div className="space-y-2 px-5">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : conversations.length === 0 ? (
        <EmptyState
          title="Aún no hay mensajes"
          action={
            <PrimaryLink href={rutaAjustes("conexiones", "whatsapp")}>Conectar WhatsApp</PrimaryLink>
          }
        >
          Falta conectar tu WhatsApp. Cuando un cliente te escriba, su conversación aparece aquí.
        </EmptyState>
      ) : (
        <>
          <div className="shrink-0 px-5">
            {visibles.length > 1 && (
              <div className="-mb-4">
                <Tabs
                  active={tab}
                  onChange={(k) => setElegida(k as TabKey)}
                  tabs={visibles.map((k) => ({ key: k, label: TAB_LABEL[k], count: counts[k] }))}
                />
              </div>
            )}
            <div className="mb-3">
              <SearchInput value={query} onChange={setQuery} placeholder="Buscar cliente o número" />
            </div>
          </div>

          <ul className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            {rows.length === 0 && (
              <li className="px-3 py-10 text-center text-cuerpo text-ink-3">
                {query ? "Nadie coincide con tu búsqueda." : "No hay conversaciones aquí."}
              </li>
            )}
            {rows.map((c) => (
              <Fila key={c.id} c={c} activa={c.id === activeId} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Fila({ c, activa }: { c: ConversationItem; activa: boolean }) {
  const hoy = contestoHoy(c);
  const esCorreo = c.channel === "correo";
  const cuando = c.last_at ? haceTiempo(c.last_at) : "·";
  const vista = c.last_message
    ? (c.last_direction === "in" ? "" : "Tú: ") + c.last_message
    : "Sin mensajes";
  return (
    <li>
      <Link
        href={`/conversaciones?id=${c.id}`}
        aria-current={activa ? "true" : undefined}
        className={`block rounded-lg px-3 py-2.5 ${activa ? "bg-surface elev-sm" : "hover:bg-fill"}`}
      >
        <p className="flex items-center gap-2">
          {hoy && <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />}
          <span
            className={`min-w-0 flex-1 truncate text-cuerpo text-ink ${hoy ? "font-semibold" : "font-medium"}`}
          >
            {tituloDe(c)}
          </span>
          {cuando !== "·" && (
            <span className={`shrink-0 text-rotulo ${hoy ? "font-medium text-accent-ink" : "text-ink-3"}`}>
              {hoy ? "Contestó hoy" : cuando}
            </span>
          )}
        </p>
        <p className={`mt-0.5 truncate text-apoyo ${hoy ? "text-ink-2" : "text-ink-3"}`}>
          {esCorreo ? "Correo · " : ""}
          {c.human_takeover ? "Tú atiendes · " : ""}
          {vista}
        </p>
      </Link>
    </li>
  );
}
