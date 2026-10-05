"use client";

import { useEffect, useMemo, useState } from "react";
import { api, mxn, type CustomerItem, type ProductItem } from "@/lib/api";
import { Drawer } from "@/components/drawer";
import { PrimaryButton, PrimaryLink, QuietButton, SecondaryButton, inputCls } from "@/components/ui";
import { toast } from "@/components/toast";

type Linea = { product: ProductItem; cantidad: number };

/** El dueño arma una cotización: cliente, productos y descuento. Se redacta con sus
 *  precios reales y queda en Hoy para que la apruebe. */
export function NuevaCotizacion({
  open,
  onClose,
  productos,
}: {
  open: boolean;
  onClose: () => void;
  productos: ProductItem[];
}) {
  const [clientes, setClientes] = useState<CustomerItem[]>([]);
  const [cliente, setCliente] = useState<CustomerItem | null>(null);
  const [buscaCliente, setBuscaCliente] = useState("");
  const [buscaProd, setBuscaProd] = useState("");
  const [lineas, setLineas] = useState<Linea[]>([]);
  const [descuento, setDescuento] = useState(0);
  const [enviando, setEnviando] = useState(false);
  const [creada, setCreada] = useState(false);

  // Carga la lista de clientes al abrir (una vez).
  useEffect(() => {
    if (open && clientes.length === 0) api.customers().then(setClientes).catch(() => {});
  }, [open, clientes.length]);

  // Reinicia el formulario cada vez que se abre.
  useEffect(() => {
    if (open) {
      setCliente(null);
      setBuscaCliente("");
      setBuscaProd("");
      setLineas([]);
      setDescuento(0);
      setCreada(false);
    }
  }, [open]);

  const clientesFiltrados = useMemo(() => {
    const q = buscaCliente.trim().toLowerCase();
    if (!q) return [];
    return clientes.filter((c) => c.name.toLowerCase().includes(q)).slice(0, 6);
  }, [clientes, buscaCliente]);

  const prodsFiltrados = useMemo(() => {
    const q = buscaProd.trim().toLowerCase();
    if (!q) return [];
    const yaIds = new Set(lineas.map((l) => l.product.id));
    return productos
      .filter((p) => !yaIds.has(p.id) && (p.name.toLowerCase().includes(q) || (p.sku ?? "").toLowerCase().includes(q)))
      .slice(0, 6);
  }, [productos, buscaProd, lineas]);

  const subtotal = lineas.reduce((s, l) => s + (l.product.price ?? 0) * l.cantidad, 0);

  const agregar = (p: ProductItem) => {
    setLineas((prev) => [...prev, { product: p, cantidad: 1 }]);
    setBuscaProd("");
  };
  const setCantidad = (id: string, n: number) =>
    setLineas((prev) => prev.map((l) => (l.product.id === id ? { ...l, cantidad: Math.max(1, n) } : l)));
  const quitar = (id: string) => setLineas((prev) => prev.filter((l) => l.product.id !== id));

  const generar = async () => {
    if (!cliente || lineas.length === 0 || enviando) return;
    setEnviando(true);
    try {
      await api.createQuote({
        customer_id: cliente.id,
        items: lineas.map((l) => ({ product_id: l.product.id, cantidad: l.cantidad })),
        descuento_pct: descuento || 0,
      });
      toast("Cotización redactada. Queda en Hoy para que la apruebes.", "success");
      setCreada(true);
    } catch (e) {
      toast(e instanceof Error ? e.message : "No se pudo redactar la cotización.", "error");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Drawer open={open} onClose={onClose} title="Nueva cotización" subtitle="Con los precios de tu catálogo">
      {creada ? (
        <div>
          <p className="text-seccion font-semibold text-ink">Cotización redactada</p>
          <p className="mt-2 text-cuerpo text-ink-2">
            Queda en Hoy para que la apruebes. Ahí la revisas, la ajustas si quieres y decides si se
            envía.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <PrimaryLink href="/">Ir a Hoy</PrimaryLink>
            <SecondaryButton onClick={onClose}>Cerrar</SecondaryButton>
          </div>
        </div>
      ) : (
        <div className="space-y-7">
          {/* Cliente */}
          <div>
            <label className="text-cuerpo font-semibold text-ink">Cliente</label>
            {cliente ? (
              <div className="mt-2 flex items-center justify-between gap-3 rounded-lg bg-panel py-1.5 pl-4 pr-1.5">
                <span className="min-w-0 truncate text-cuerpo text-ink">{cliente.name}</span>
                <button onClick={() => setCliente(null)} className="btn btn-quiet btn-sm shrink-0">
                  Cambiar
                </button>
              </div>
            ) : (
              <div className="relative mt-2">
                <input
                  value={buscaCliente}
                  onChange={(e) => setBuscaCliente(e.target.value)}
                  placeholder="Busca un cliente"
                  aria-label="Buscar cliente"
                  className={inputCls}
                />
                {clientesFiltrados.length > 0 && (
                  <div className="elev-md absolute z-10 mt-1 w-full overflow-hidden rounded-xl bg-surface p-1">
                    {clientesFiltrados.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => { setCliente(c); setBuscaCliente(""); }}
                        className="block w-full truncate rounded-md px-3 py-2 text-left text-cuerpo text-ink hover:bg-fill"
                      >
                        {c.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Productos */}
          <div>
            <label className="text-cuerpo font-semibold text-ink">Productos</label>
            <div className="relative mt-2">
              <input
                value={buscaProd}
                onChange={(e) => setBuscaProd(e.target.value)}
                placeholder="Busca un producto para agregarlo"
                aria-label="Buscar producto"
                className={inputCls}
              />
              {prodsFiltrados.length > 0 && (
                <div className="elev-md absolute z-10 mt-1 w-full overflow-hidden rounded-xl bg-surface p-1">
                  {prodsFiltrados.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => agregar(p)}
                      className="flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-cuerpo text-ink hover:bg-fill"
                    >
                      <span className="min-w-0 truncate">{p.name}</span>
                      <span className="tnum shrink-0 text-ink-3">{p.price != null ? mxn(p.price) : "Sin precio"}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {lineas.length > 0 && (
              <div className="mt-2">
                {lineas.map((l) => (
                  <div key={l.product.id} className="flex items-center gap-3 border-b border-line py-2.5 last:border-0">
                    <span className="min-w-0 flex-1 truncate text-cuerpo text-ink">{l.product.name}</span>
                    <input
                      type="number"
                      min={1}
                      value={l.cantidad}
                      onChange={(e) => setCantidad(l.product.id, Number(e.target.value))}
                      aria-label={`Cantidad de ${l.product.name}`}
                      className={`${inputCls} tnum !w-20 text-right`}
                    />
                    <span className="tnum w-24 shrink-0 text-right text-cuerpo text-ink-2">
                      {mxn((l.product.price ?? 0) * l.cantidad)}
                    </span>
                    <button onClick={() => quitar(l.product.id)} className="btn btn-quiet btn-sm shrink-0">
                      Quitar
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Descuento + total */}
          <div className="flex items-end justify-between gap-3">
            <label className="flex items-center gap-2 text-cuerpo font-semibold text-ink">
              Descuento
              <input
                type="number"
                min={0}
                max={100}
                value={descuento}
                onChange={(e) => setDescuento(Number(e.target.value))}
                className={`${inputCls} tnum !w-20 text-right font-normal`}
              />
              <span className="font-normal text-ink-3">%</span>
            </label>
            <div className="text-right">
              <p className="text-apoyo text-ink-3">Subtotal</p>
              <p className="tnum text-seccion font-semibold text-ink">{mxn(subtotal)}</p>
            </div>
          </div>
          <p className="text-apoyo text-ink-3">
            El descuento no pasa del máximo que le pusiste a tu ayudante de Ventas; el IVA y la vigencia
            salen de sus ajustes. Nada se envía sin tu aprobación.
          </p>

          <div className="flex items-center gap-2">
            <PrimaryButton onClick={generar} disabled={!cliente || lineas.length === 0 || enviando}>
              {enviando ? "Redactando…" : "Redactar cotización"}
            </PrimaryButton>
            <QuietButton onClick={onClose}>Cancelar</QuietButton>
          </div>
        </div>
      )}
    </Drawer>
  );
}
