"use client";

// Panel izquierdo del master-detail de Conversaciones: la bandeja unificada (WhatsApp +
// correo) que se queda fija mientras abres un hilo a la derecha. Vive en el layout de la
// sección, así no se recarga al cambiar de hilo. Conserva el triage (identificar / ligar /
// descartar); la fila del hilo abierto queda resaltada.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  api,
  type ConversationItem,
  type ConversationStatus,
  type CustomerItem,
} from "@/lib/api";
import { toast } from "@/components/toast";
import {
  EmptyState,
  ErrorState,
  PrimaryButton,
  PrimaryLink,
  SearchInput,
  SecondaryButton,
  Skeleton,
  Tabs,
  useApi,
} from "@/components/ui";
import { haceTiempo } from "@/lib/format";

type TabKey = "identificados" | "por_identificar" | "descartados";

const STATUS_TAB: Record<ConversationStatus, TabKey> = {
  identificado: "identificados",
  por_identificar: "por_identificar",
  descartado: "descartados",
};

export function ConversationsList() {
  const { data, error, loading, refetch } = useApi(api.conversations);
  const [tab, setTab] = useState<TabKey>("por_identificar");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const activeId = useSearchParams().get("id");

  const conversations = data ?? [];
  // Clientes existentes para "ligar a uno que ya tengo" en vez de crear otro.
  const [clientes, setClientes] = useState<CustomerItem[]>([]);
  useEffect(() => {
    api.customers("cliente").then(setClientes).catch(() => {});
  }, [data]);

  const counts = useMemo(() => {
    const c = { identificados: 0, por_identificar: 0, descartados: 0 };
    for (const x of conversations) c[STATUS_TAB[x.status]]++;
    return c;
  }, [conversations]);

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
      );
  }, [conversations, tab, query]);

  async function act(fn: () => Promise<unknown>, id: string, ok?: string) {
    setBusy(id);
    try {
      await fn();
      if (ok) toast(ok, "info");
      await refetch();
    } catch (e) {
      toast(e instanceof Error ? e.message : "No se pudo completar la acción.", "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 px-4 pb-2.5 pt-3.5">
        <h1 className="text-cuerpo font-semibold tracking-tight text-ink">Conversaciones</h1>
        <p className="mt-0.5 text-apoyo text-ink-3">WhatsApp y correo, en una bandeja.</p>
      </header>

      {error ? (
        <div className="px-4">
          <ErrorState message={error} retry={refetch} />
        </div>
      ) : loading ? (
        <div className="space-y-2 px-3">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[52px] w-full rounded-lg" />
          ))}
        </div>
      ) : conversations.length === 0 ? (
        <div className="px-3">
          <EmptyState
            title="Sin conversaciones"
            action={
              <PrimaryLink href="/integraciones/detalle?key=whatsapp">
                Conectar WhatsApp
              </PrimaryLink>
            }
          >
            Cuando te escriban por WhatsApp o correo, sus hilos aparecerán aquí.
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="shrink-0 px-3">
            <Tabs
              active={tab}
              onChange={(k) => setTab(k as TabKey)}
              tabs={[
                { key: "identificados", label: "Identificados", count: counts.identificados },
                { key: "por_identificar", label: "Por identificar", count: counts.por_identificar },
                { key: "descartados", label: "Descartadas", count: counts.descartados },
              ]}
            />
            <div className="mb-2">
              <SearchInput value={query} onChange={setQuery} placeholder="Buscar cliente o número…" />
            </div>
          </div>

          <ul className="min-h-0 flex-1 divide-y divide-line/70 overflow-y-auto">
            {rows.length === 0 && (
              <li className="px-4 py-10 text-center text-cuerpo text-ink-3">
                Nada aquí{query ? " para tu búsqueda" : ""}.
              </li>
            )}
            {rows.map((c) => (
              <ConversationRow
                key={c.id}
                c={c}
                active={c.id === activeId}
                busy={busy === c.id}
                clientes={clientes}
                onRegister={(opts) =>
                  act(
                    () => api.registrarClienteConversacion(c.id, opts),
                    c.id,
                    opts.linkCustomerId
                      ? "Conversación ligada al cliente."
                      : "Cliente dado de alta. La conversación quedó identificada.",
                  )
                }
                onDismiss={() =>
                  act(() => api.dismissConversation(c.id), c.id, "Conversación descartada.")
                }
                onUndismiss={() =>
                  act(() => api.undismissConversation(c.id), c.id, "De vuelta en la bandeja.")
                }
              />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

const fieldCls =
  "min-w-0 flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none";

function ConversationRow({
  c,
  active,
  busy,
  clientes,
  onRegister,
  onDismiss,
  onUndismiss,
}: {
  c: ConversationItem;
  active: boolean;
  busy: boolean;
  clientes: CustomerItem[];
  onRegister: (opts: { name?: string; linkCustomerId?: string }) => void;
  onDismiss: () => void;
  onUndismiss: () => void;
}) {
  const [registering, setRegistering] = useState(false);
  const [name, setName] = useState("");
  const [linkId, setLinkId] = useState("");
  const cuando = c.last_at ? haceTiempo(c.last_at) : "·";
  const esCorreo = c.channel === "correo";
  const contacto = esCorreo ? c.correo?.de || "correo sin remitente" : c.remote_phone;
  const title = c.customer ?? (esCorreo ? c.correo?.nombre || contacto : c.remote_phone);
  const preview = c.last_message
    ? (c.last_direction === "in" ? "" : "Tú: ") + c.last_message
    : "Sin mensajes";
  return (
    <li className={`px-2 py-1 ${active ? "bg-accent-soft/50" : ""}`}>
      <Link
        href={`/conversaciones?id=${c.id}`}
        className={`block rounded-lg px-2 py-2 transition-colors ${
          active ? "" : "hover:bg-panel/60"
        }`}
      >
        <p className="flex items-center gap-2 text-cuerpo font-medium text-ink">
          <span className="min-w-0 flex-1 truncate">{title}</span>
          {cuando !== "·" && <span className="shrink-0 text-sello font-normal text-ink-3">{cuando}</span>}
        </p>
        <p className="mt-0.5 flex items-center gap-1.5">
          <span className="shrink-0 rounded bg-panel px-1.5 py-px text-sello font-medium text-ink-2">
            {esCorreo ? "Correo" : "WhatsApp"}
          </span>
          {c.human_takeover && (
            <span className="shrink-0 rounded border border-line px-2 py-0.5 text-rotulo font-medium text-ink-2">
              tú al mando
            </span>
          )}
          <span className="min-w-0 flex-1 truncate text-apoyo text-ink-3">{preview}</span>
        </p>
      </Link>

      <div className="flex items-center gap-1.5 px-2 pb-1.5">
        {c.status === "identificado" && c.customer_id && (
          <Link
            href={`/clientes/detalle?id=${c.customer_id}`}
            className="text-apoyo font-medium text-accent-ink transition-colors hover:underline"
          >
            Ver ficha
          </Link>
        )}
        {c.status === "por_identificar" && (
          <button
            onClick={() => setRegistering((v) => !v)}
            disabled={busy}
            className="text-apoyo font-medium text-accent-ink transition-colors hover:underline disabled:opacity-50"
          >
            {registering ? "Cerrar" : "Registrar cliente"}
          </button>
        )}
        <button
          onClick={c.status === "descartado" ? onUndismiss : onDismiss}
          disabled={busy}
          className="ml-auto text-apoyo text-ink-3 transition-colors hover:text-ink disabled:opacity-50"
        >
          {c.status === "descartado" ? "Deshacer" : "Descartar"}
        </button>
      </div>

      {/* Un contacto por identificar no es cliente aún: lígalo a uno que ya tengas o crea uno. */}
      {registering && c.status === "por_identificar" && (
        <div className="mx-2 mb-2 rounded-lg border border-line bg-panel/50 p-2.5">
          <p className="text-apoyo leading-relaxed text-ink-3">
            {esCorreo ? "El correo" : "El número"}{" "}
            <span className="tnum font-medium text-ink-2">{contacto}</span> aún no es de nadie.
          </p>
          {clientes.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <select value={linkId} onChange={(e) => setLinkId(e.target.value)} className={fieldCls}>
                <option value="">Ligar a un cliente…</option>
                {clientes.map((cl) => (
                  <option key={cl.id} value={cl.id}>
                    {cl.name}
                  </option>
                ))}
              </select>
              <SecondaryButton onClick={() => onRegister({ linkCustomerId: linkId })} disabled={!linkId || busy}>
                Ligar
              </SecondaryButton>
            </div>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="…o crea uno: nombre del cliente"
              className={fieldCls}
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim()) onRegister({ name: name.trim() });
              }}
            />
            <PrimaryButton onClick={() => onRegister({ name: name.trim() })} disabled={!name.trim() || busy}>
              Crear
            </PrimaryButton>
          </div>
        </div>
      )}
    </li>
  );
}
