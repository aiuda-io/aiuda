"use client";

// Lo que confirmas en aiuda (un pago, un cambio de cliente, un alta) se escribe de
// regreso en el sistema de donde vino el dato. Aquí se ve en qué va cada cosa: en
// espera, ya registrada o si no se pudo, con lo que respondió ese sistema y cuándo, y
// el reintento a mano de lo que falló.
// Si el registro no tiene nada que escribir (vino de Excel: no hay a dónde), no pinta nada.

import { useState } from "react";
import { api, type WritebackEntry } from "@/lib/api";
import { SOURCE_LABEL, SOURCE_LOGO, useApi } from "@/components/ui";
import { toast } from "@/components/toast";
import { fechaHora } from "@/lib/format";
import { leerFallo, plural } from "@/lib/cartera";

const cifra = (n: number) =>
  n.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const CAMPO: Record<string, string> = { name: "nombre", email: "correo", phone: "teléfono" };

// Altas: algo que nació en aiuda y viaja al sistema que el dueño eligió.
const ALTA: Record<string, string> = {
  crear_cliente: "Alta del cliente",
  crear_producto: "Alta del producto",
  crear_factura: "Alta de la factura",
  crear_cita: "Alta de la cita",
};

function sistema(e: WritebackEntry): string {
  return e.target_label && e.target_label !== e.target ? e.target_label : (SOURCE_LABEL[e.target] ?? e.target);
}

function titulo(e: WritebackEntry): string {
  const donde = sistema(e);
  if (e.action === "registrar_pago") {
    // Sin el monto: la cola no guarda la moneda, y pintarlo como pesos podría mentir.
    return `Pago de ${e.folio ?? "la factura"} en ${donde}`;
  }
  if (e.action === "actualizar_cliente") {
    const campos = Object.keys(e.changes ?? {}).map((k) => CAMPO[k] ?? k);
    return `Datos del cliente${campos.length ? ` (${campos.join(", ")})` : ""} en ${donde}`;
  }
  if (ALTA[e.action]) {
    return `${ALTA[e.action]}${e.folio ? ` ${e.folio}` : ""} en ${donde}`;
  }
  return `Cambio en ${donde}`;
}

function detalle(e: WritebackEntry): string {
  const donde = sistema(e);
  if (e.estado === "inyectada") {
    const r = e.evidencia?.respuesta ?? {};
    const cuando = e.evidencia?.en ? `, ${fechaHora(e.evidencia.en)}` : "";
    if (r.detalle) return `${r.detalle}${cuando}`;
    if (r.modo === "pago") {
      const saldo =
        r.saldo_odoo == null
          ? ""
          : r.saldo_odoo > 0
            ? `. Allá todavía le quedan ${cifra(r.saldo_odoo)} por cobrar`
            : ". Allá ya no debe nada";
      return `Pago registrado en ${donde}${cuando}${saldo}`;
    }
    if (r.modo === "nota") return `Quedó como nota en ${donde}${cuando}`;
    if (e.action === "actualizar_cliente") {
      return r.creado
        ? `No existía en ${donde}: se dio de alta${cuando}`
        : `Cliente actualizado en ${donde}${cuando}`;
    }
    if (ALTA[e.action]) {
      return `Quedó de alta en ${donde}${r.ref ? ` con la referencia ${r.ref}` : ""}${cuando}`;
    }
    return `Registrado en ${donde}${cuando}`;
  }
  // Lo que respondió el otro sistema viene en crudo (y en inglés): no se le enseña al
  // dueño. Se dice qué pasó y qué puede hacer.
  if (e.estado === "falló") {
    return `No se pudo registrar en ${donde} después de ${plural(e.attempts, "intento", "intentos")}. Revisa que ${donde} siga conectado y reintenta.`;
  }
  // Falló un intento solo si dejó su error: `attempts` ya viene en 1 mientras el
  // primer envío sigue en camino.
  if (e.last_error || e.reintento_en) {
    const cuando = e.reintento_en ? ` después de las ${fechaHora(e.reintento_en)}` : "";
    return `${donde} no respondió. aiuda lo vuelve a intentar${cuando}.`;
  }
  return `Está por mandarse a ${donde}. Si no sale ahora, aiuda lo manda en su siguiente revisión, que hace cada hora en punto mientras está abierta.`;
}

const ESTADO: Record<string, [string, string]> = {
  inyectada: ["var(--color-ok)", "Registrado"],
  pendiente: ["var(--color-ink-3)", "En espera"],
  "falló": ["var(--color-danger)", "No se pudo"],
};

export function WritebackStatus({
  invoiceId,
  customerId,
  refreshKey,
}: {
  invoiceId?: string;
  customerId?: string;
  refreshKey?: string;
}) {
  const { data, refetchQuiet } = useApi<{ entries: WritebackEntry[] }>(
    () => api.writeback({ invoice_id: invoiceId, customer_id: customerId }),
    [invoiceId, customerId, refreshKey],
  );
  const [busy, setBusy] = useState<string | null>(null);

  const entries = data?.entries ?? [];
  if (entries.length === 0) return null; // nada que escribir, nada que reportar

  async function reintentar(id: string) {
    setBusy(id);
    try {
      await api.retryWriteback(id);
      toast("Reintentando…", "info");
      await refetchQuiet();
      // El intento corre aparte: un vistazo más para traer cómo quedó.
      setTimeout(() => refetchQuiet(), 4000);
    } catch (e) {
      toast(leerFallo(e).mensaje, "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="border-t border-line pt-5">
      <h3 className="text-cuerpo font-semibold text-ink">Lo que aiuda escribió en tus sistemas</h3>
      <ul className="mt-3 space-y-4">
        {entries.map((e) => {
          const [color, palabra] = ESTADO[e.estado] ?? ESTADO.pendiente;
          return (
            <li key={e.id}>
              <div className="flex items-start gap-3">
                {SOURCE_LOGO[e.target] && (
                  <img src={SOURCE_LOGO[e.target]} alt="" className="mt-1 h-4 w-4 shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-cuerpo text-ink">{titulo(e)}</p>
                  <p className="mark mt-0.5" style={{ "--mark": color } as React.CSSProperties}>
                    {palabra}
                  </p>
                  <p className="mt-1 text-apoyo text-ink-3">{detalle(e)}</p>
                  {e.estado === "falló" && (
                    <button
                      onClick={() => reintentar(e.id)}
                      disabled={busy !== null}
                      className="btn btn-sm btn-secondary mt-2"
                    >
                      {busy === e.id ? "Reintentando…" : "Reintentar"}
                    </button>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
