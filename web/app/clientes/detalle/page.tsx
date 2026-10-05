"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, type CustomerDetail, type ChatMessage } from "@/lib/api";
import { dinero } from "@/lib/cartera";
import { fechaDM } from "@/lib/format";
import {
  BucketPill,
  ErrorState,
  PrimaryButton,
  SecondaryButton,
  SecondaryLink,
  Skeleton,
  SOURCE_LABEL,
  TextInput,
  useApi,
} from "@/components/ui";
import { usePageTrail } from "@/components/rastro";
import { Chatter, type ChatterMessage } from "@/components/chatter";
import { ProvenanceBar, fuenteEspejo as fuenteDe, espejoLiga } from "@/components/provenance";
import { toast } from "@/components/toast";
import { TagChip, TagPicker } from "@/components/tags";
import { WritebackStatus } from "@/components/writeback-status";
import { InyectarButton } from "@/components/inyectar-button";
import type { Tag } from "@/lib/api";

const REMINDER_ESTADO: Record<string, string> = {
  draft: "Borrador",
  pending_approval: "Por aprobar",
  approved: "Aprobado",
  sent: "Enviado",
  rejected: "Rechazado",
  failed: "No salió",
};

function toChatter(messages: ChatMessage[], customerName: string): ChatterMessage[] {
  return messages.map((m) => {
    const mine = m.direction === "out";
    return {
      id: m.id,
      side: mine ? "me" : "them",
      label: mine ? (m.author === "human" ? "Tú" : "Tu ayudante") : customerName,
      avatar: mine && m.author !== "human" ? "/aiudante.png" : undefined,
      body: m.body,
      time: m.created_at,
    };
  });
}

export default function ClienteDetallePage() {
  // useSearchParams exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={null}>
      <ClienteDetalle />
    </Suspense>
  );
}

function ClienteDetalle() {
  const id = useSearchParams().get("id") ?? "";
  const { data, error, loading, refetch } = useApi<CustomerDetail>(() => api.customerDetail(id), [id]);
  usePageTrail(data?.name ?? (data?.kind === "prospecto" ? "Prospecto" : "Cliente"));
  const [optimistic, setOptimistic] = useState<ChatMessage[]>([]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<{
    name: string;
    email: string;
    phone: string;
    meta: Record<string, string>;
  }>({ name: "", email: "", phone: "", meta: {} });
  const [newField, setNewField] = useState({ key: "", value: "" });
  const [saving, setSaving] = useState(false);
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  // Tras encolar una inyección, el "Regreso a la fuente" del riel se recarga
  // (su refreshKey depende de los datos del cliente, que no cambian al encolar).
  const [inyKey, setInyKey] = useState(0);

  useEffect(() => {
    if (data) {
      setDraft({
        name: data.name,
        email: data.email ?? "",
        phone: data.phone ?? "",
        meta: { ...(data.meta ?? {}) },
      });
      setSelectedTags(data.tags ?? []);
    }
  }, [data]);

  function addField() {
    const key = newField.key.trim();
    if (!key) return;
    setDraft((d) => ({ ...d, meta: { ...d.meta, [key]: newField.value.trim() } }));
    setNewField({ key: "", value: "" });
  }

  function removeField(key: string) {
    setDraft((d) => {
      const meta = { ...d.meta };
      delete meta[key];
      return { ...d, meta };
    });
  }

  useEffect(() => {
    api.tags().then(setAllTags).catch(() => {});
  }, []);

  async function persistTags(ids: string[]) {
    if (!data) return;
    setSelectedTags(ids);
    await api.setCustomerTags(data.id, ids).catch(() => toast("No se pudo guardar la etiqueta.", "error"));
  }

  function toggleTag(id: string) {
    persistTags(selectedTags.includes(id) ? selectedTags.filter((t) => t !== id) : [...selectedTags, id]);
  }

  async function createTag(name: string) {
    try {
      const tag = await api.createTag(name);
      setAllTags((prev) => [...prev, tag]);
      await persistTags([...selectedTags, tag.id]);
    } catch (e) {
      toast(`No se pudo crear la etiqueta: ${(e as Error).message}`, "error");
    }
  }

  if (error) return <ErrorState message={error} retry={refetch} />;

  // Dedup por id: tras enviar agregamos el mensaje optimista y refetcheamos; el
  // refetch ya trae ese mismo mensaje del server, así que sin dedup salía 2 veces.
  const messages = data
    ? [...data.messages, ...optimistic].filter(
        (m, i, arr) => arr.findIndex((x) => x.id === m.id) === i,
      )
    : [];
  // Procedencia: si el registro vive en un sistema externo, aiuda lo ESPEJA (los datos
  // maestros mandan allá y se editan allá). Si no, nació en aiuda y aiuda es la fuente. La
  // detección vive en el componente compartido para no divergir entre clientes/facturas/productos.
  const fuenteEspejo = fuenteDe(data?.presence);
  const esEspejo = fuenteEspejo !== null;
  const espejoUrl = espejoLiga(data?.presence);
  // Editable en aiuda solo si es nativo (o un prospecto, que vive aquí): un espejo se edita
  // en su fuente para no romper la verdad. Las etiquetas siempre son tuyas (nativas de aiuda).
  const editableAqui = data?.kind === "prospecto" || !esEspejo;

  // El envío por WhatsApp corre en segundo plano (respuesta instantánea); aquí solo
  // mostramos el mensaje al instante. try/catch para que un tropiezo del API avise con
  // un toast en vez de rechazar la promesa y verse como un "issue" de Next.
  async function send(body: string) {
    if (!data) return;
    try {
      const sent = await api.messageCustomer(data.id, body);
      setOptimistic((prev) => [...prev, sent]);
      refetch();
    } catch (e) {
      toast(`No se pudo enviar: ${(e as Error).message}`, "error");
    }
  }

  async function sendFile(file: File, caption: string) {
    if (!data) return;
    try {
      const sent = await api.attachToCustomer(data.id, file, caption);
      setOptimistic((prev) => [...prev, sent]);
      refetch();
    } catch (e) {
      toast(`No se pudo adjuntar: ${(e as Error).message}`, "error");
    }
  }

  async function saveEdit() {
    if (!data) return;
    setSaving(true);
    try {
      const res = await api.editCustomer(data.id, draft);
      if (res.writeback.length > 0) {
        const donde = res.writeback.map((s) => SOURCE_LABEL[s] ?? s).join(" y ");
        toast(`Cliente actualizado aquí. El cambio todavía no se escribe en ${donde}: queda anotado.`, "success");
      } else {
        toast("Cliente actualizado.", "success");
      }
      setEditing(false);
      refetch();
    } catch (e) {
      toast(`No se pudo guardar: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  const primerNombre = data?.name.split(" ")[0] ?? "";

  return (
    <div className="min-w-0">
      {loading && !data ? (
        <div className="space-y-6">
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-5 w-64" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : data ? (
        <div className="reveal">
          {editing ? (
            <section className="mb-10 max-w-3xl">
              <h1 className="text-titulo font-semibold text-ink">Editar a {data.name}</h1>
              <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
                <label className="block">
                  <span className="text-rotulo text-ink-2">Nombre</span>
                  <TextInput className="mt-1.5" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
                </label>
                <label className="block">
                  <span className="text-rotulo text-ink-2">WhatsApp</span>
                  <TextInput className="mt-1.5" value={draft.phone} placeholder="Opcional" onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))} />
                </label>
                <label className="block">
                  <span className="text-rotulo text-ink-2">Correo</span>
                  <TextInput className="mt-1.5" value={draft.email} placeholder="Opcional" onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))} />
                </label>
              </div>

              {/* Datos extra editables: tan flexible como tu Excel, no solo tres campos. */}
              <h2 className="mt-8 text-seccion font-semibold text-ink">Otros datos</h2>
              <div className="mt-3 space-y-2">
                {Object.entries(draft.meta).map(([key, value]) => (
                  <div key={key} className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)_auto] items-center gap-2">
                    <span className="truncate text-cuerpo text-ink-2" title={key}>
                      {key}
                    </span>
                    <TextInput
                      aria-label={key}
                      value={value}
                      onChange={(e) => setDraft((d) => ({ ...d, meta: { ...d.meta, [key]: e.target.value } }))}
                    />
                    <button onClick={() => removeField(key)} className="btn btn-quiet btn-sm">
                      Quitar
                    </button>
                  </div>
                ))}
                <div className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)_auto] items-center gap-2">
                  <TextInput
                    placeholder="Dato: RFC"
                    aria-label="Nombre del dato"
                    value={newField.key}
                    onChange={(e) => setNewField((f) => ({ ...f, key: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") addField();
                    }}
                  />
                  <TextInput
                    placeholder="Valor"
                    aria-label="Valor del dato"
                    value={newField.value}
                    onChange={(e) => setNewField((f) => ({ ...f, value: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") addField();
                    }}
                  />
                  <SecondaryButton size="sm" onClick={addField} disabled={!newField.key.trim()}>
                    Agregar
                  </SecondaryButton>
                </div>
              </div>

              {/* Solo se edita aquí lo que nació en aiuda (o un prospecto); lo que viene de
                  otro sistema se edita allá, así que no llega a este formulario. */}
              <p className="mt-5 text-apoyo text-ink-3">
                {data.kind === "prospecto"
                  ? "Un prospecto vive solo en aiuda hasta que se vuelva cliente. El cambio se guarda aquí."
                  : "Este cliente se dio de alta en aiuda. El cambio se guarda aquí."}
              </p>
              <div className="mt-5 flex gap-2">
                <PrimaryButton onClick={saveEdit} disabled={saving}>
                  {saving ? "Guardando…" : "Guardar"}
                </PrimaryButton>
                <SecondaryButton onClick={() => setEditing(false)}>Cancelar</SecondaryButton>
              </div>
            </section>
          ) : (
            <>
              {/* De dónde viene: lo que vive en otro sistema se edita allá; lo de aiuda, aquí. */}
              <ProvenanceBar
                presence={data.presence}
                nativeLabel={data.kind === "prospecto" ? "Prospecto en aiuda" : "Dado de alta en aiuda"}
              />

              <header className="mb-10 mt-6 flex flex-wrap items-end justify-between gap-x-10 gap-y-6">
                <div className="min-w-0 flex-1 basis-80">
                  <div className="flex min-w-0 items-center gap-3">
                    <h1 className="min-w-0 truncate text-titulo font-semibold text-ink" title={data.name}>
                      {data.name}
                    </h1>
                    {data.kind === "prospecto" && <span className="mark shrink-0">Prospecto</span>}
                  </div>
                  <p className="tnum mt-2 truncate text-cuerpo text-ink-2">
                    {data.phone ? `WhatsApp ${data.phone}` : "Sin teléfono"}
                    {data.email ? ` · ${data.email}` : ""}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    {selectedTags
                      .map((tid) => allTags.find((t) => t.id === tid))
                      .filter((t): t is Tag => !!t)
                      .map((t) => (
                        <TagChip key={t.id} tag={t} onRemove={() => toggleTag(t.id)} />
                      ))}
                    <TagPicker allTags={allTags} selectedIds={selectedTags} onToggle={toggleTag} onCreate={createTag} />
                  </div>
                  <div className="mt-5 flex flex-wrap items-center gap-2">
                    {editableAqui ? (
                      <SecondaryButton size="sm" onClick={() => setEditing(true)}>
                        Editar
                      </SecondaryButton>
                    ) : espejoUrl ? (
                      <SecondaryLink href={espejoUrl} external size="sm">
                        Editar en {SOURCE_LABEL[fuenteEspejo] ?? fuenteEspejo}
                      </SecondaryLink>
                    ) : null}
                    {/* Mandar el cliente a tu otro sistema. Solo clientes (un prospecto vive
                        en aiuda) y solo a donde todavía no esté. */}
                    {data.kind === "cliente" && (
                      <InyectarButton
                        entidad="cliente"
                        id={data.id}
                        presence={data.presence}
                        small
                        onQueued={() => {
                          setInyKey((n) => n + 1);
                          refetch();
                        }}
                      />
                    )}
                  </div>
                </div>
                {data.kind !== "prospecto" && (
                  <div className="shrink-0">
                    <p className="eyebrow">Te debe</p>
                    <p className="hero-num mt-1 whitespace-nowrap text-cifra text-ink">
                      {dinero(data.open_total, data.moneda)}
                    </p>
                    {(data.por_moneda ?? [])
                      .filter((s) => s.moneda !== data.moneda)
                      .map((s) => (
                        <p key={s.moneda} className="tnum mt-1 text-seccion font-semibold text-ink">
                          {dinero(s.open_total, s.moneda)}
                        </p>
                      ))}
                    <p className="mt-1 text-apoyo text-ink-3">
                      {data.open_count === 0
                        ? "Sin facturas abiertas"
                        : `en ${data.open_count} ${data.open_count === 1 ? "factura abierta" : "facturas abiertas"}`}
                    </p>
                  </div>
                )}
              </header>

              {/* Pidió no recibir mensajes (escribió BAJA). Mientras siga así, no le llega
                  nada automático; tú puedes escribirle. Reactivarlo lo decides tú. */}
              {data.opt_out && (
                <div className="mb-10 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl bg-warn-soft px-5 py-4">
                  <div className="min-w-0 flex-1 basis-72">
                    <p className="text-cuerpo font-semibold text-ink">
                      Pidió no recibir mensajes
                      {data.opt_out.via === "whatsapp" ? " (escribió BAJA por WhatsApp)" : " (lo marcaste tú)"}
                    </p>
                    <p className="mt-1 text-cuerpo text-ink-2">
                      Desde el {fechaDM(data.opt_out.at)} tu ayudante no le manda recordatorios. Tú sí puedes
                      escribirle.
                    </p>
                  </div>
                  <SecondaryButton
                    onClick={async () => {
                      try {
                        await api.setCustomerOptOut(data.id, false);
                        toast("El cliente vuelve a recibir mensajes.", "success");
                        refetch();
                      } catch (e) {
                        toast(`No se pudo reactivar: ${(e as Error).message}`, "error");
                      }
                    }}
                  >
                    Permitir de nuevo
                  </SecondaryButton>
                </div>
              )}
            </>
          )}

          {/* Una sola vista, sin pestañas: sus facturas y su conversación al centro; al
              lado, lo que ya pasó con este cliente. En pantallas angostas se apila. */}
          <div className="grid gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
            <div className="min-w-0 space-y-10">
              <Seccion titulo="Facturas" cuenta={data.invoices.length}>
                {data.invoices.length === 0 ? (
                  <p className="text-cuerpo text-ink-3">Todavía no tiene facturas.</p>
                ) : (
                  <ul>
                    {data.invoices.map((inv) => (
                      <li key={inv.id} className="border-b border-line last:border-0">
                        <Link
                          href={`/facturas/detalle?id=${inv.id}`}
                          className="-mx-3 flex items-center gap-4 rounded-lg px-3 py-3 hover:bg-panel"
                        >
                          <span className="tnum min-w-0 truncate text-cuerpo font-medium text-ink">{inv.folio}</span>
                          {inv.status === "paid" ? (
                            <span className="mark" style={{ "--mark": "var(--color-ok)" } as React.CSSProperties}>
                              Pagada
                            </span>
                          ) : (
                            <BucketPill bucket={inv.bucket} />
                          )}
                          <span className="tnum ml-auto shrink-0 text-cuerpo font-semibold text-ink">
                            {dinero(inv.amount, inv.currency)}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Seccion>

              <section>
                <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <h2 className="text-seccion font-semibold text-ink">
                    Conversación
                    {messages.length > 0 && <span className="tnum ml-2 font-normal text-ink-3">{messages.length}</span>}
                  </h2>
                  {data.conversation_id && (
                    <Link
                      href={`/conversaciones?id=${data.conversation_id}`}
                      className="text-apoyo font-medium text-accent-ink hover:underline"
                    >
                      Abrir en Mensajes
                    </Link>
                  )}
                </div>
                <Chatter
                  messages={toChatter(messages, data.name)}
                  onSend={send}
                  onSendFile={sendFile}
                  channel={{ active: "whatsapp", options: ["email"] }}
                  placeholder={`Escríbele a ${primerNombre}`}
                  emptyTitle={`Aún no le has escrito a ${primerNombre}`}
                  emptyHint="Lo que escribas sale de tu parte por WhatsApp."
                />
              </section>
            </div>

            <aside className="min-w-0 space-y-10">
              {data.payments.length > 0 && (
                <Seccion titulo="Pagos recibidos">
                  <ul>
                    {data.payments.map((p) => (
                      <Renglon key={p.id}>
                        <span className="tnum text-cuerpo font-medium text-ink">{dinero(p.amount, p.currency)}</span>
                        {p.folio && <span className="tnum truncate text-apoyo text-ink-3">{p.folio}</span>}
                        <span className="ml-auto shrink-0 text-apoyo text-ink-3">{fechaDM(p.paid_at)}</span>
                      </Renglon>
                    ))}
                  </ul>
                </Seccion>
              )}

              {data.reminders.length > 0 && (
                <Seccion titulo="Recordatorios de cobro">
                  <ul>
                    {data.reminders.map((r) => (
                      <Renglon key={r.id}>
                        <span className="text-cuerpo text-ink">{REMINDER_ESTADO[r.status] ?? r.status}</span>
                        {r.folio && <span className="tnum truncate text-apoyo text-ink-3">{r.folio}</span>}
                        <span className="ml-auto shrink-0 text-apoyo text-ink-3">{fechaDM(r.created_at)}</span>
                      </Renglon>
                    ))}
                  </ul>
                </Seccion>
              )}

              {data.promises.length > 0 && (
                <Seccion titulo="Promesas de pago">
                  <ul>
                    {data.promises.map((p) => (
                      <Renglon key={p.id}>
                        <span className="text-cuerpo text-ink">Para el {fechaDM(p.promised_date)}</span>
                        {p.folio && <span className="tnum truncate text-apoyo text-ink-3">{p.folio}</span>}
                        <span
                          className="mark ml-auto shrink-0"
                          style={p.fulfilled ? ({ "--mark": "var(--color-ok)" } as React.CSSProperties) : undefined}
                        >
                          {p.fulfilled ? "Cumplida" : "Pendiente"}
                        </span>
                      </Renglon>
                    ))}
                  </ul>
                </Seccion>
              )}

              {data.citas.length > 0 && (
                <Seccion titulo="Agenda">
                  <ul>
                    {data.citas.map((c) => (
                      <Renglon key={c.id}>
                        <span className="min-w-0 truncate text-cuerpo text-ink">{c.title}</span>
                        {c.starts_at && (
                          <span className="ml-auto shrink-0 text-apoyo text-ink-3">{fechaDM(c.starts_at)}</span>
                        )}
                      </Renglon>
                    ))}
                  </ul>
                </Seccion>
              )}

              {!editing && Object.keys(data.meta ?? {}).length > 0 && (
                <Seccion titulo="Otros datos">
                  <dl>
                    {Object.entries(data.meta).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-4 border-b border-line py-2.5 text-cuerpo last:border-0">
                        <dt className="shrink-0 text-ink-3">{k}</dt>
                        <dd className="min-w-0 truncate text-right font-medium text-ink" title={v}>
                          {v}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </Seccion>
              )}

              {/* Si un cambio a este cliente ya quedó escrito en su otro sistema. Se recarga
                  al guardar y al mandar el cliente desde el encabezado. */}
              <WritebackStatus
                customerId={id}
                refreshKey={`${data.name}|${data.phone ?? ""}|${data.email ?? ""}|${inyKey}`}
              />
            </aside>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Seccion({ titulo, cuenta, children }: { titulo: string; cuenta?: number; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-seccion font-semibold text-ink">
        {titulo}
        {typeof cuenta === "number" && cuenta > 0 && (
          <span className="tnum ml-2 font-normal text-ink-3">{cuenta}</span>
        )}
      </h2>
      {children}
    </section>
  );
}

function Renglon({ children }: { children: React.ReactNode }) {
  return <li className="flex items-center gap-3 border-b border-line py-2.5 last:border-0">{children}</li>;
}
