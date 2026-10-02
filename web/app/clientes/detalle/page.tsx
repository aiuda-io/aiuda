"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, mxn, type CustomerDetail, type ChatMessage } from "@/lib/api";
import { fechaDM } from "@/lib/format";
import { BucketPill, ErrorState, PrimaryButton, SecondaryButton, SecondaryLink, Skeleton, SOURCE_LABEL, useApi } from "@/components/ui";
import { RailLayout } from "@/components/rail";
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
  failed: "Falló",
};

function toChatter(messages: ChatMessage[], customerName: string): ChatterMessage[] {
  return messages.map((m) => {
    const mine = m.direction === "out";
    return {
      id: m.id,
      side: mine ? "me" : "them",
      label: mine ? (m.author === "human" ? "Tú" : "Ayudante") : customerName,
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
        toast(
          `Cliente actualizado. Queda en cola para inyectarse a ${res.writeback.map((s) => SOURCE_LABEL[s] ?? s).join(" y ")} cuando habilitemos la escritura del cliente.`,
          "success",
        );
      } else {
        toast("Cliente actualizado en aiuda.", "success");
      }
      setEditing(false);
      refetch();
    } catch (e) {
      toast(`No se pudo guardar: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  const inputCls =
    "w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none";

  return (
    <div className="min-w-0">
      {loading && !data ? (
        <div className="space-y-4">
          <Skeleton className="h-8 w-40 rounded-lg" />
          <div className="flex items-end justify-between gap-3">
            <div className="space-y-2">
              <Skeleton className="h-6 w-52 rounded-lg" />
              <Skeleton className="h-3.5 w-64 rounded" />
            </div>
            <Skeleton className="h-8 w-28 rounded-lg" />
          </div>
          <div className="grid gap-5 lg:grid-cols-[1fr_minmax(0,20rem)]">
            <Skeleton className="h-80 rounded-lg" />
            <div className="space-y-3">
              <Skeleton className="h-28 rounded-lg" />
              <Skeleton className="h-20 rounded-lg" />
            </div>
          </div>
        </div>
      ) : data ? (
        <div className="reveal">
          {editing ? (
            <div className="mb-5 max-w-3xl rounded-lg border border-line bg-surface p-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div>
                  <label className="text-rotulo uppercase tracking-[0.06em] text-ink-3">Nombre</label>
                  <input className={`mt-1 ${inputCls}`} value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
                </div>
                <div>
                  <label className="text-rotulo uppercase tracking-[0.06em] text-ink-3">WhatsApp</label>
                  <input className={`mt-1 ${inputCls}`} value={draft.phone} placeholder="opcional" onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))} />
                </div>
                <div>
                  <label className="text-rotulo uppercase tracking-[0.06em] text-ink-3">Correo</label>
                  <input className={`mt-1 ${inputCls}`} value={draft.email} onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))} placeholder="opcional" />
                </div>
              </div>

              {/* Datos extra editables: tan flexible como tu Excel, no solo 3 campos */}
              <div className="mt-4 border-t border-line/60 pt-3">
                <p className="text-rotulo uppercase tracking-[0.06em] text-ink-3">Datos extra</p>
                <div className="mt-2 space-y-2">
                  {Object.entries(draft.meta).map(([key, value]) => (
                    <div key={key} className="grid grid-cols-[8rem_1fr_auto] items-center gap-2">
                      <span className="truncate text-cuerpo text-ink-2" title={key}>
                        {key}
                      </span>
                      <input
                        className={inputCls}
                        value={value}
                        onChange={(e) =>
                          setDraft((d) => ({ ...d, meta: { ...d.meta, [key]: e.target.value } }))
                        }
                      />
                      <button
                        onClick={() => removeField(key)}
                        title="Quitar campo"
                        className="rounded-md border border-line px-2.5 py-1.5 text-cuerpo leading-none text-ink-3 transition-colors hover:border-danger hover:text-danger"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                  <div className="grid grid-cols-[8rem_1fr_auto] items-center gap-2 border-t border-line/40 pt-2.5">
                    <input
                      className={inputCls}
                      placeholder="Campo (RFC…)"
                      value={newField.key}
                      onChange={(e) => setNewField((f) => ({ ...f, key: e.target.value }))}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") addField();
                      }}
                    />
                    <input
                      className={inputCls}
                      placeholder="Valor"
                      value={newField.value}
                      onChange={(e) => setNewField((f) => ({ ...f, value: e.target.value }))}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") addField();
                      }}
                    />
                    <SecondaryButton onClick={addField} disabled={!newField.key.trim()}>
                      Agregar
                    </SecondaryButton>
                  </div>
                </div>
              </div>

              {/* Solo se edita aquí lo nativo de aiuda (prospecto o registro creado aquí);
                  un espejo se edita en su fuente, así que no llega a este formulario. */}
              <p className="mt-3 text-apoyo leading-relaxed text-ink-3">
                {data.kind === "prospecto"
                  ? "Un prospecto vive en aiuda hasta que se vuelva cliente; el cambio se guarda aquí y no se inyecta a Odoo ni a tu tienda."
                  : "Este registro nació en aiuda; aquí es la fuente de verdad. El cambio se guarda directo."}
              </p>
              <div className="mt-3 flex gap-2">
                <PrimaryButton onClick={saveEdit} disabled={saving}>
                  {saving ? "Guardando…" : "Guardar"}
                </PrimaryButton>
                <SecondaryButton onClick={() => setEditing(false)}>Cancelar</SecondaryButton>
              </div>
            </div>
          ) : (
            <>
              {/* Procedencia al frente: un espejo se edita en su fuente; un nativo, aquí. */}
              <ProvenanceBar
                presence={data.presence}
                nativeLabel={data.kind === "prospecto" ? "Prospecto en aiuda" : "Registro nativo de aiuda"}
              />

              {/* Opt-out: el cliente pidió no recibir mensajes (BAJA/STOP). Mientras esté
                  activo, ningún recordatorio automatizado le llega; tú puedes escribirle en
                  persona. Reactivar es decisión del dueño (soberanía humana, trazable). */}
              {data.opt_out && (
                <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-warn/40 bg-warn-soft/40 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-cuerpo font-medium text-ink">
                      Pidió no recibir mensajes ({data.opt_out.via === "whatsapp" ? "escribió BAJA por WhatsApp" : "marcado desde la consola"})
                    </p>
                    <p className="mt-0.5 text-apoyo leading-relaxed text-ink-2">
                      Desde el {fechaDM(data.opt_out.at)} no se le envían recordatorios ni
                      seguimientos automáticos. Tú puedes seguir escribiéndole en persona.
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

              <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2.5">
                    <h1 className="text-seccion font-semibold tracking-tight text-ink">{data.name}</h1>
                    {data.kind === "prospecto" && (
                      <span className="rounded bg-panel px-1.5 py-px text-rotulo font-medium uppercase tracking-[0.04em] text-ink-3">
                        Prospecto
                      </span>
                    )}
                    {editableAqui ? (
                      <SecondaryButton size="sm" onClick={() => setEditing(true)}>
                        Editar
                      </SecondaryButton>
                    ) : espejoUrl ? (
                      <SecondaryLink href={espejoUrl} external size="sm">
                        Editar en {SOURCE_LABEL[fuenteEspejo] ?? fuenteEspejo} ↗
                      </SecondaryLink>
                    ) : null}
                    {/* Empujar el cliente al maestro elegido. Solo clientes (el copy del
                        prospecto promete que vive en aiuda) y solo destinos donde no viva ya. */}
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
                  <p className="tnum mt-0.5 text-cuerpo text-ink-3">
                    {data.phone ? `WhatsApp · ${data.phone}` : "Sin teléfono aún"}
                    {data.email ? ` · ${data.email}` : ""}
                  </p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {selectedTags
                    .map((id) => allTags.find((t) => t.id === id))
                    .filter((t): t is Tag => !!t)
                    .map((t) => (
                      <TagChip key={t.id} tag={t} onRemove={() => toggleTag(t.id)} />
                    ))}
                  <TagPicker allTags={allTags} selectedIds={selectedTags} onToggle={toggleTag} onCreate={createTag} />
                </div>
              </div>
              <div className="text-right">
                <p className="hero-num text-titulo font-semibold leading-none text-ink">{mxn(data.open_total)}</p>
                <p className="text-apoyo text-ink-3">
                  por cobrar · {data.open_count} {data.open_count === 1 ? "factura" : "facturas"}
                </p>
              </div>
              </header>
            </>
          )}

          {/* Una sola vista, sin pestañas: primero su cartera y saldo (lo que importa de un
              cliente en cobranza), y debajo la conversación. Todo a la mano, sin cambiar de tab. */}
          <RailLayout
              rail={
                <>
                  {data.payments.length > 0 && (
                    <section>
                      <h2 className="mb-2 text-seccion font-semibold text-ink">Pagos recibidos</h2>
                      <ul className="overflow-hidden rounded-lg border border-line bg-surface">
                        {data.payments.map((p) => (
                          <li key={p.id} className="flex items-center gap-2 border-b border-line/60 px-4 py-2.5 last:border-0">
                            <span className="tnum text-cuerpo font-medium text-ink">{mxn(p.amount)}</span>
                            {p.folio && <span className="tnum text-apoyo text-ink-3">{p.folio}</span>}
                            <span className="ml-auto text-apoyo text-ink-3">{fechaDM(p.paid_at)}</span>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}

                  {data.reminders.length > 0 && (
                    <section>
                      <h2 className="mb-2 text-seccion font-semibold text-ink">Recordatorios</h2>
                      <ul className="overflow-hidden rounded-lg border border-line bg-surface">
                        {data.reminders.map((r) => (
                          <li key={r.id} className="flex items-center gap-2 border-b border-line/60 px-4 py-2.5 last:border-0">
                            {r.folio && <span className="tnum text-cuerpo font-medium text-ink">{r.folio}</span>}
                            <span className="text-apoyo text-ink-3">{REMINDER_ESTADO[r.status] ?? r.status}</span>
                            <span className="ml-auto text-apoyo text-ink-3">{fechaDM(r.created_at)}</span>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}

                  {data.promises.length > 0 && (
                    <section>
                      <h2 className="mb-2 text-seccion font-semibold text-ink">Promesas de pago</h2>
                      <ul className="overflow-hidden rounded-lg border border-line bg-surface">
                        {data.promises.map((p) => (
                          <li key={p.id} className="flex items-center gap-2 border-b border-line/60 px-4 py-2.5 last:border-0">
                            <span className="text-cuerpo text-ink">Prometió {fechaDM(p.promised_date)}</span>
                            {p.folio && <span className="tnum text-apoyo text-ink-3">{p.folio}</span>}
                            <span className={`ml-auto text-apoyo font-medium ${p.fulfilled ? "text-ok" : "text-ink-3"}`}>
                              {p.fulfilled ? "Cumplida" : "Pendiente"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}

                  {data.citas.length > 0 && (
                    <section>
                      <h2 className="mb-2 text-seccion font-semibold text-ink">Citas</h2>
                      <ul className="overflow-hidden rounded-lg border border-line bg-surface">
                        {data.citas.map((c) => (
                          <li key={c.id} className="flex items-center gap-2 border-b border-line/60 px-4 py-2.5 last:border-0">
                            <span className="truncate text-cuerpo text-ink">{c.title}</span>
                            {c.starts_at && <span className="ml-auto shrink-0 text-apoyo text-ink-3">{fechaDM(c.starts_at)}</span>}
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}

                  {!editing && Object.keys(data.meta ?? {}).length > 0 && (
                    <section>
                      <h2 className="mb-2 text-seccion font-semibold text-ink">Datos extra</h2>
                      <dl className="space-y-1.5 rounded-lg border border-line bg-surface px-4 py-3">
                        {Object.entries(data.meta).map(([k, v]) => (
                          <div key={k} className="flex justify-between gap-3 text-cuerpo">
                            <dt className="text-ink-3">{k}</dt>
                            <dd className="font-medium text-ink">{v}</dd>
                          </div>
                        ))}
                      </dl>
                    </section>
                  )}

                  {/* Write-back: si la edición del cliente ya quedó escrita en su fuente.
                      El refreshKey recarga tras guardar (los datos del maestro cambian)
                      y tras encolar una inyección desde el encabezado. */}
                  <WritebackStatus
                    customerId={id}
                    refreshKey={`${data.name}|${data.phone ?? ""}|${data.email ?? ""}|${inyKey}`}
                  />
                </>
              }
            >
              {/* Cartera al frente: es lo que importa de un cliente en cobranza. */}
              <section>
                <h2 className="mb-2 text-seccion font-semibold text-ink">Facturas</h2>
                {data.invoices.length === 0 ? (
                  <p className="rounded-lg border border-line bg-surface px-4 py-6 text-center text-cuerpo text-ink-3">
                    Sin facturas registradas.
                  </p>
                ) : (
                  <ul className="overflow-hidden rounded-lg border border-line bg-surface">
                    {data.invoices.map((inv) => (
                      <li key={inv.id} className="border-b border-line/60 last:border-0">
                        <Link
                          href={`/facturas/detalle?id=${inv.id}`}
                          className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-panel/40"
                        >
                          <span className="tnum text-cuerpo font-medium text-ink">{inv.folio}</span>
                          {inv.status === "paid" ? (
                            <span className="rounded bg-ok-soft px-1.5 py-px text-sello font-medium text-ok">Pagada</span>
                          ) : (
                            <BucketPill bucket={inv.bucket} />
                          )}
                          <span className="tnum ml-auto text-cuerpo font-medium text-ink">{mxn(inv.amount)}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </RailLayout>

            {/* Conversación en la misma vista, debajo de la cartera. Chatter acotado (no llena
                la pantalla): es un registro de cliente con su hilo a la mano, no un chat a solas. */}
            <section className="reveal mt-8">
              <h2 className="mb-2.5 text-seccion font-semibold text-ink">
                Conversación
                {messages.length > 0 && (
                  <span className="tnum ml-1.5 font-normal text-ink-3">· {messages.length}</span>
                )}
              </h2>
              <Chatter
                messages={toChatter(messages, data.name)}
                onSend={send}
                onSendFile={sendFile}
                channel={{ active: "whatsapp", options: ["email", "slack"] }}
                placeholder={`Escríbele a ${data.name.split(" ")[0]}…`}
                emptyTitle={`Aún no le has escrito a ${data.name.split(" ")[0]}`}
                emptyHint="Lo que escribas sale de tu parte por WhatsApp. Tu ayudante sigue atento al hilo."
              />
            </section>
        </div>
      ) : null}
    </div>
  );
}
