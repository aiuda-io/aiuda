"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, mxn, type CustomerItem, type ProductItem } from "@/lib/api";
import { Drawer } from "@/components/drawer";
import { PrimaryButton, SecondaryButton } from "@/components/ui";
import { toast } from "@/components/toast";

type Linea = { product: ProductItem; cantidad: number };

/** Drawer para que el dueño arme una cotización: elige cliente + productos + descuento.
 *  Se genera con precios reales y queda en Aprobaciones. */
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
      toast("Cotización lista en Aprobaciones", "success");
      setCreada(true);
    } catch (e) {
      toast(e instanceof Error ? e.message : "No se pudo generar", "error");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Drawer open={open} onClose={onClose} title="Nueva cotización" subtitle="Se arma con tus precios reales">
      {creada ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-[13px] text-ink-2">
            Tu cotización quedó redactada y espera tu aprobación. Revísala, ajústala si quieres y envíala.
          </p>
          <Link href="/centro" className="text-[13px] font-medium text-accent-ink hover:underline">
            Ir a Aprobaciones →
          </Link>
          <SecondaryButton onClick={onClose}>Cerrar</SecondaryButton>
        </div>
      ) : (
        <div className="space-y-5">
          {/* Cliente */}
          <div>
            <label className="text-[12px] font-semibold text-ink">Cliente</label>
            {cliente ? (
              <div className="mt-1.5 flex items-center justify-between rounded-md border border-line bg-panel/40 px-3 py-2">
                <span className="text-[13px] text-ink">{cliente.name}</span>
                <button onClick={() => setCliente(null)} className="text-[12px] text-ink-3 hover:text-ink">
                  Cambiar
                </button>
              </div>
            ) : (
              <div className="relative mt-1.5">
                <input
                  value={buscaCliente}
                  onChange={(e) => setBuscaCliente(e.target.value)}
                  placeholder="Busca un cliente…"
                  className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
                />
                {clientesFiltrados.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-md border border-line bg-surface shadow-lg">
                    {clientesFiltrados.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => { setCliente(c); setBuscaCliente(""); }}
                        className="block w-full px-3 py-2 text-left text-[13px] text-ink hover:bg-accent-soft"
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
            <label className="text-[12px] font-semibold text-ink">Productos</label>
            <div className="relative mt-1.5">
              <input
                value={buscaProd}
                onChange={(e) => setBuscaProd(e.target.value)}
                placeholder="Busca un producto para agregar…"
                className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
              />
              {prodsFiltrados.length > 0 && (
                <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-md border border-line bg-surface shadow-lg">
                  {prodsFiltrados.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => agregar(p)}
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-[13px] text-ink hover:bg-accent-soft"
                    >
                      <span>{p.name}</span>
                      <span className="text-ink-3">{p.price != null ? mxn(p.price) : "sin precio"}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {lineas.length > 0 && (
              <div className="mt-2.5 space-y-1.5">
                {lineas.map((l) => (
                  <div key={l.product.id} className="flex items-center gap-2 rounded-md border border-line px-3 py-2">
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{l.product.name}</span>
                    <input
                      type="number"
                      min={1}
                      value={l.cantidad}
                      onChange={(e) => setCantidad(l.product.id, Number(e.target.value))}
                      className="w-14 rounded border border-line bg-surface px-1.5 py-1 text-right text-[12.5px] text-ink focus:border-accent focus:outline-none"
                    />
                    <span className="w-20 text-right text-[12.5px] text-ink-2">
                      {mxn((l.product.price ?? 0) * l.cantidad)}
                    </span>
                    <button onClick={() => quitar(l.product.id)} aria-label="Quitar" className="text-ink-3 hover:text-danger">
                      &times;
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Descuento + total */}
          <div className="flex items-center justify-between gap-3">
            <label className="text-[12px] font-semibold text-ink">
              Descuento
              <input
                type="number"
                min={0}
                max={100}
                value={descuento}
                onChange={(e) => setDescuento(Number(e.target.value))}
                className="ml-2 w-16 rounded border border-line bg-surface px-1.5 py-1 text-right text-[12.5px] text-ink focus:border-accent focus:outline-none"
              />
              <span className="ml-1 text-[12px] text-ink-3">%</span>
            </label>
            <div className="text-right">
              <p className="text-[11px] text-ink-3">Subtotal</p>
              <p className="text-[15px] font-semibold tabular-nums text-ink">{mxn(subtotal)}</p>
            </div>
          </div>
          <p className="text-[11px] text-ink-3">
            El descuento se topa al máximo que configuraste; el IVA y la vigencia salen de las perillas
            de la aiudita. Tú apruebas antes de enviar.
          </p>

          <div className="flex items-center gap-2">
            <PrimaryButton onClick={generar} disabled={!cliente || lineas.length === 0 || enviando}>
              {enviando ? "Generando…" : "Generar cotización"}
            </PrimaryButton>
            <SecondaryButton onClick={onClose}>Cancelar</SecondaryButton>
          </div>
        </div>
      )}
    </Drawer>
  );
}
