"use client";

// "Agregar" con captura directa. aiuda NO es tu sistema maestro, pero captura
// rápido: el registro nace aquí (procedencia honesta "Creado en aiuda") y, si
// marcas un destino, el alta VIAJA también a tu maestro (Odoo, Google Calendar,
// tu propia API con escritura) vía el write-back. Debajo siguen los caminos de
// siempre: crear en la fuente (deep-link), traer muchos (Excel/conectar) o ligar
// una conversación. Crear local siempre se puede; nada bloquea.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  api,
  type CustomerItem,
  type EntidadInyectable,
  type InyeccionEncolada,
  type InyectarDestino,
} from "@/lib/api";
import { Drawer } from "@/components/drawer";
import { toast } from "@/components/toast";
import { PrimaryButton } from "@/components/ui";
import { settingsInputCls } from "@/components/settings";

type Tipo = "clientes" | "productos" | "facturas" | "citas";

const ENTIDAD: Record<Tipo, EntidadInyectable> = {
  clientes: "cliente",
  productos: "producto",
  facturas: "factura",
  citas: "cita",
};

type ObjSource = {
  source: string | null;
  source_label: string | null;
  new_url: string | null;
  native: boolean;
};

function Campo({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-rotulo uppercase tracking-[0.06em] text-ink-3">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function OptionCard({
  href,
  external,
  onClose,
  title,
  desc,
}: {
  href: string;
  external?: boolean;
  onClose: () => void;
  title: string;
  desc: string;
}) {
  const cls =
    "block rounded-lg border border-line bg-surface px-3.5 py-3 transition-colors hover:border-line-strong hover:bg-panel/40";
  const body = (
    <>
      <p className="text-cuerpo font-medium text-ink">{title}</p>
      <p className="mt-0.5 text-apoyo leading-relaxed text-ink-3">{desc}</p>
    </>
  );
  if (external) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={cls}>
        {body}
      </a>
    );
  }
  return (
    <Link href={href} onClick={onClose} className={cls}>
      {body}
    </Link>
  );
}

export function AgregarSheet({
  open,
  onClose,
  tipo,
  label,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  tipo: Tipo;
  label: string; // singular: "cliente", "producto", "factura", "cita"
  /** Recarga de la lista de la página tras crear (pásale el refetch de useApi). */
  onCreated?: () => void;
}) {
  const entidad = ENTIDAD[tipo];
  const femenino = entidad === "factura" || entidad === "cita";
  const [src, setSrc] = useState<ObjSource | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  // Destinos que hoy pueden recibir el alta (derivado de credenciales reales).
  const [destinos, setDestinos] = useState<InyectarDestino[]>([]);
  const [inyectar, setInyectar] = useState(false);
  const [destinoIdx, setDestinoIdx] = useState(0);

  // Selector buscable de clientes (solo facturas).
  const [clientes, setClientes] = useState<CustomerItem[]>([]);
  const [clienteQuery, setClienteQuery] = useState("");
  const [clienteId, setClienteId] = useState("");
  const [listaAbierta, setListaAbierta] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSrc(null);
    setDraft({});
    setBusy(false);
    setInyectar(false);
    setDestinoIdx(0);
    setClienteQuery("");
    setClienteId("");
    setListaAbierta(false);
    api.objectSource(tipo).then(setSrc).catch(() => {});
    api
      .inyectarDestinos()
      .then((d) => setDestinos(d[entidad] ?? []))
      .catch(() => setDestinos([]));
    if (tipo === "facturas") api.customers().then(setClientes).catch(() => {});
  }, [open, tipo, entidad]);

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setDraft((d) => ({ ...d, [k]: e.target.value }));
  const v = (k: string) => draft[k] ?? "";
  const num = (k: string): number | undefined => {
    const s = v(k).trim();
    if (!s) return undefined;
    const n = Number(s);
    return Number.isFinite(n) ? n : undefined;
  };

  const coincidencias = useMemo(() => {
    const q = clienteQuery.trim().toLowerCase();
    return clientes
      .filter((c) => !q || c.name.toLowerCase().includes(q) || (c.phone ?? "").includes(q))
      .slice(0, 8);
  }, [clientes, clienteQuery]);

  const destinoSel = destinos[destinoIdx] ?? destinos[0] ?? null;

  const valido =
    tipo === "clientes" || tipo === "productos"
      ? v("name").trim().length > 0
      : tipo === "citas"
        ? v("title").trim().length > 0
        : Boolean(clienteId) &&
          v("folio").trim().length > 0 &&
          (num("amount") ?? 0) > 0 &&
          v("due_date").trim().length > 0;

  async function guardar() {
    setBusy(true);
    try {
      const extra =
        inyectar && destinoSel
          ? { inyectar_a: destinoSel.target, conexion_id: destinoSel.conexion_id }
          : {};
      let inyeccion: InyeccionEncolada = null;
      if (tipo === "clientes") {
        const r = await api.createCustomer({
          name: v("name").trim(),
          phone: v("phone").trim() || undefined,
          email: v("email").trim() || undefined,
          ...extra,
        });
        inyeccion = r.inyeccion;
      } else if (tipo === "productos") {
        const r = await api.createProduct({
          name: v("name").trim(),
          sku: v("sku").trim() || undefined,
          price: num("price"),
          stock: num("stock"),
          unit: v("unit").trim() || undefined,
          ...extra,
        });
        inyeccion = r.inyeccion;
      } else if (tipo === "facturas") {
        const r = await api.createInvoice({
          customer_id: clienteId,
          folio: v("folio").trim(),
          amount: num("amount") ?? 0,
          due_date: v("due_date"),
          concepto: v("concepto").trim() || undefined,
          ...extra,
        });
        inyeccion = r.inyeccion;
      } else {
        const r = await api.createAppointment({
          title: v("title").trim(),
          starts_at: v("starts_at") || undefined,
          customer_name: v("customer_name").trim() || undefined,
          notes: v("notes").trim() || undefined,
          ...extra,
        });
        inyeccion = r.inyeccion;
      }
      const creado = femenino ? "creada" : "creado";
      const cap = label.charAt(0).toUpperCase() + label.slice(1);
      toast(
        inyeccion && destinoSel
          ? `${cap} ${creado}; viajando a ${destinoSel.label}.`
          : `${cap} ${creado} en aiuda.`,
        "success",
      );
      onCreated?.();
      onClose();
    } catch (e) {
      // 409/422 traen el porqué legible del backend (folio repetido, sin hora…).
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={`Agregar ${label}`}
      subtitle="Captura rápida; tus fuentes siguen mandando"
    >
      <div className="space-y-3">
        {/* Formulario local: el camino primario. El registro nace en aiuda con
            procedencia honesta; el check de abajo lo manda además a tu maestro. */}
        <div className="space-y-3">
          {tipo === "clientes" && (
            <>
              <Campo label="Nombre">
                <input className={settingsInputCls} value={v("name")} onChange={set("name")} placeholder="Ferretería El Martillo" />
              </Campo>
              <div className="grid grid-cols-2 gap-3">
                <Campo label="WhatsApp">
                  <input className={settingsInputCls} value={v("phone")} onChange={set("phone")} placeholder="229 123 4567" />
                </Campo>
                <Campo label="Correo">
                  <input className={settingsInputCls} type="email" value={v("email")} onChange={set("email")} placeholder="opcional" />
                </Campo>
              </div>
            </>
          )}

          {tipo === "productos" && (
            <>
              <Campo label="Nombre">
                <input className={settingsInputCls} value={v("name")} onChange={set("name")} placeholder="Tornillo 3/4" />
              </Campo>
              <div className="grid grid-cols-2 gap-3">
                <Campo label="SKU">
                  <input className={settingsInputCls} value={v("sku")} onChange={set("sku")} placeholder="opcional" />
                </Campo>
                <Campo label="Precio">
                  <input className={settingsInputCls} inputMode="decimal" value={v("price")} onChange={set("price")} placeholder="0.00" />
                </Campo>
                <Campo label="Existencia">
                  <input className={settingsInputCls} inputMode="decimal" value={v("stock")} onChange={set("stock")} placeholder="opcional" />
                </Campo>
                <Campo label="Unidad">
                  <input className={settingsInputCls} value={v("unit")} onChange={set("unit")} placeholder="pza, kg…" />
                </Campo>
              </div>
            </>
          )}

          {tipo === "facturas" && (
            <>
              <Campo label="Cliente">
                <div className="relative">
                  <input
                    className={settingsInputCls}
                    value={clienteQuery}
                    onChange={(e) => {
                      setClienteQuery(e.target.value);
                      setClienteId("");
                      setListaAbierta(true);
                    }}
                    onFocus={() => setListaAbierta(true)}
                    placeholder={clientes.length === 0 ? "Aún no tienes clientes" : "Busca por nombre o teléfono…"}
                  />
                  {listaAbierta && !clienteId && coincidencias.length > 0 && (
                    <ul className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-line bg-surface shadow-[0_8px_24px_rgba(13,45,62,0.12)]">
                      {coincidencias.map((c) => (
                        <li key={c.id}>
                          <button
                            type="button"
                            onClick={() => {
                              setClienteId(c.id);
                              setClienteQuery(c.name);
                              setListaAbierta(false);
                            }}
                            className="flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left text-cuerpo text-ink transition-colors hover:bg-panel/50"
                          >
                            <span className="truncate">{c.name}</span>
                            {c.phone && <span className="tnum shrink-0 text-apoyo text-ink-3">{c.phone}</span>}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </Campo>
              {clientes.length === 0 && (
                <p className="text-apoyo text-ink-3">
                  La factura se cuelga de un cliente. Crea uno primero desde{" "}
                  <Link href="/clientes" onClick={onClose} className="font-medium text-accent-ink hover:underline">
                    Clientes
                  </Link>
                  .
                </p>
              )}
              <div className="grid grid-cols-2 gap-3">
                <Campo label="Folio">
                  <input className={settingsInputCls} value={v("folio")} onChange={set("folio")} placeholder="F-104" />
                </Campo>
                <Campo label="Monto">
                  <input className={settingsInputCls} inputMode="decimal" value={v("amount")} onChange={set("amount")} placeholder="0.00" />
                </Campo>
                <Campo label="Vence">
                  <input className={settingsInputCls} type="date" value={v("due_date")} onChange={set("due_date")} />
                </Campo>
                <Campo label="Concepto">
                  <input className={settingsInputCls} value={v("concepto")} onChange={set("concepto")} placeholder="opcional" />
                </Campo>
              </div>
            </>
          )}

          {tipo === "citas" && (
            <>
              <Campo label="Título">
                <input className={settingsInputCls} value={v("title")} onChange={set("title")} placeholder="Revisión anual" />
              </Campo>
              <div className="grid grid-cols-2 gap-3">
                <Campo label="Fecha y hora">
                  <input className={settingsInputCls} type="datetime-local" value={v("starts_at")} onChange={set("starts_at")} />
                </Campo>
                <Campo label="Cliente">
                  <input className={settingsInputCls} value={v("customer_name")} onChange={set("customer_name")} placeholder="opcional" />
                </Campo>
              </div>
              <Campo label="Notas">
                <textarea className={`${settingsInputCls} min-h-16 resize-y`} value={v("notes")} onChange={set("notes")} placeholder="opcional" />
              </Campo>
            </>
          )}

          {/* Crear también en un maestro: solo si HOY hay destinos que reciben
              esta entidad (Odoo/Calendar con credencial o conexión que escribe). */}
          {destinos.length > 0 && (
            <div className="rounded-lg border border-line bg-panel/30 px-3.5 py-3">
              <label className="flex cursor-pointer items-start gap-2.5">
                <input
                  type="checkbox"
                  checked={inyectar}
                  onChange={(e) => setInyectar(e.target.checked)}
                  className="mt-0.5 accent-[var(--color-accent)]"
                />
                <span className="min-w-0">
                  <span className="block text-cuerpo font-medium text-ink">
                    {destinos.length === 1
                      ? `Crear también en ${destinos[0].label}`
                      : "Crear también en otro sistema"}
                  </span>
                  <span className="mt-0.5 block text-apoyo leading-relaxed text-ink-3">
                    El registro nace en aiuda y el alta viaja al destino en segundo plano.
                  </span>
                </span>
              </label>
              {inyectar && destinos.length > 1 && (
                <select
                  className={`${settingsInputCls} mt-2`}
                  value={destinoIdx}
                  onChange={(e) => setDestinoIdx(Number(e.target.value))}
                >
                  {destinos.map((d, i) => (
                    <option key={`${d.target}-${d.conexion_id ?? ""}`} value={i}>
                      {d.label}
                    </option>
                  ))}
                </select>
              )}
              {inyectar && tipo === "facturas" && destinoSel?.target === "odoo" && (
                <p className="mt-2 text-apoyo leading-relaxed text-ink-3">
                  A Odoo llega como borrador: revisas impuestos y la publicas allá.
                </p>
              )}
              {inyectar && tipo === "citas" && !v("starts_at") && (
                <p className="mt-2 text-apoyo leading-relaxed text-warn">
                  Para viajar al calendario, la cita necesita fecha y hora.
                </p>
              )}
            </div>
          )}

          <PrimaryButton onClick={guardar} disabled={!valido || busy}>
            {busy ? "Guardando…" : `Guardar ${label}`}
          </PrimaryButton>
        </div>

        {/* Los caminos de siempre, ahora secundarios. */}
        <p className="pt-2 text-rotulo font-semibold uppercase tracking-[0.07em] text-ink-3">
          O si prefieres…
        </p>

        {/* Crear en la fuente: se crea allá y baja como espejo en el próximo sync. */}
        {src?.new_url && src.source_label && (
          <OptionCard
            href={src.new_url}
            external
            onClose={onClose}
            title={`Crear uno en ${src.source_label} ↗`}
            desc={`Se crea en tu fuente (${src.source_label}) y baja a aiuda como espejo en el próximo sync. Los datos maestros siguen viviendo allá.`}
          />
        )}

        {/* Traer muchos */}
        <OptionCard
          href="/importar"
          onClose={onClose}
          title="Sube un Excel"
          desc="Trae muchos de golpe; la IA detecta qué es y los carga. Re-subir no duplica."
        />
        <OptionCard
          href="/integraciones"
          onClose={onClose}
          title="Conecta una fuente"
          desc="Odoo, tu tienda y más: entran solos, cada uno con su procedencia marcada."
        />

        {/* Ligar una conversación (solo clientes) */}
        {tipo === "clientes" && (
          <OptionCard
            href="/conversaciones"
            onClose={onClose}
            title="Liga una conversación de WhatsApp"
            desc="Un número que ya te escribió y es cliente: lígalo a un registro, no lo recrees."
          />
        )}
      </div>
    </Drawer>
  );
}
