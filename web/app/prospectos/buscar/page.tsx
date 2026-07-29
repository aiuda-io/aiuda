"use client";

// Prospección con el DENUE del INEGI: buscas negocios reales por giro y zona,
// previsualizas (nada se guarda) y cargas los que elijas como prospectos con
// procedencia denue. El dedupe vive en el backend: lo que ya está en tu cartera
// se marca aquí y no se duplica al cargar.

import { useMemo, useState } from "react";
import Link from "next/link";
import { api, type NegocioDenue, type ProspeccionFuente } from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  PrimaryButton,
  Skeleton,
  useApi,
} from "@/components/ui";
import { usePageTrail } from "@/components/rastro";
import { toast } from "@/components/toast";

// La API pública del DENUE busca alrededor de un PUNTO (lat,lng) con radio de
// hasta 5 km; estos centros de ciudad son el atajo (y "Coordenadas propias"
// cubre cualquier otro punto). No hay filtro por tamaño: la API de búsqueda
// por punto no lo expone.
const ZONAS: { key: string; label: string; lat: number; lng: number }[] = [
  { key: "aguascalientes", label: "Aguascalientes", lat: 21.8853, lng: -102.2916 },
  { key: "cancun", label: "Cancún", lat: 21.1619, lng: -86.8515 },
  { key: "chihuahua", label: "Chihuahua", lat: 28.632, lng: -106.0691 },
  { key: "cdmx", label: "Ciudad de México", lat: 19.4326, lng: -99.1332 },
  { key: "juarez", label: "Ciudad Juárez", lat: 31.6904, lng: -106.4245 },
  { key: "culiacan", label: "Culiacán", lat: 24.8091, lng: -107.394 },
  { key: "guadalajara", label: "Guadalajara", lat: 20.6597, lng: -103.3496 },
  { key: "hermosillo", label: "Hermosillo", lat: 29.073, lng: -110.9559 },
  { key: "leon", label: "León", lat: 21.125, lng: -101.686 },
  { key: "mazatlan", label: "Mazatlán", lat: 23.2494, lng: -106.4111 },
  { key: "merida", label: "Mérida", lat: 20.9674, lng: -89.5926 },
  { key: "mexicali", label: "Mexicali", lat: 32.6245, lng: -115.4523 },
  { key: "monterrey", label: "Monterrey", lat: 25.6866, lng: -100.3161 },
  { key: "morelia", label: "Morelia", lat: 19.706, lng: -101.195 },
  { key: "oaxaca", label: "Oaxaca", lat: 17.0732, lng: -96.7266 },
  { key: "pachuca", label: "Pachuca", lat: 20.1011, lng: -98.7591 },
  { key: "puebla", label: "Puebla", lat: 19.0414, lng: -98.2063 },
  { key: "queretaro", label: "Querétaro", lat: 20.5888, lng: -100.3899 },
  { key: "saltillo", label: "Saltillo", lat: 25.4383, lng: -101.0053 },
  { key: "slp", label: "San Luis Potosí", lat: 22.1565, lng: -100.9855 },
  { key: "tampico", label: "Tampico", lat: 22.2331, lng: -97.8611 },
  { key: "tijuana", label: "Tijuana", lat: 32.5149, lng: -117.0382 },
  { key: "toluca", label: "Toluca", lat: 19.2826, lng: -99.6557 },
  { key: "torreon", label: "Torreón", lat: 25.5428, lng: -103.4068 },
  { key: "tuxtla", label: "Tuxtla Gutiérrez", lat: 16.7516, lng: -93.1029 },
  { key: "veracruz", label: "Veracruz", lat: 19.1738, lng: -96.1342 },
  { key: "villahermosa", label: "Villahermosa", lat: 17.9895, lng: -92.9475 },
  { key: "zacatecas", label: "Zacatecas", lat: 22.7709, lng: -102.5832 },
];

const RADIOS: { m: number; label: string }[] = [
  { m: 500, label: "500 m" },
  { m: 1000, label: "1 km" },
  { m: 2500, label: "2.5 km" },
  { m: 5000, label: "5 km (máximo del INEGI)" },
];

const inputCls =
  "w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none";

export default function BuscarNegociosPage() {
  usePageTrail("Buscar negocios");
  const fuente = useApi<ProspeccionFuente>(() => api.prospeccionFuente(), []);

  const [condicion, setCondicion] = useState("");
  const [zona, setZona] = useState("monterrey");
  const [latProp, setLatProp] = useState("");
  const [lngProp, setLngProp] = useState("");
  const [radio, setRadio] = useState(2500);

  const [buscando, setBuscando] = useState(false);
  const [resultado, setResultado] = useState<NegocioDenue[] | null>(null);
  const [errorBusqueda, setErrorBusqueda] = useState<string | null>(null);
  const [seleccion, setSeleccion] = useState<Set<string>>(new Set());
  const [cargando, setCargando] = useState(false);

  const zonaSel = ZONAS.find((z) => z.key === zona);
  const punto =
    zona === "propias"
      ? { lat: parseFloat(latProp), lng: parseFloat(lngProp) }
      : { lat: zonaSel?.lat ?? NaN, lng: zonaSel?.lng ?? NaN };
  const puntoValido = Number.isFinite(punto.lat) && Number.isFinite(punto.lng);
  const puedeBuscar = condicion.trim().length > 0 && puntoValido && !buscando;

  async function buscar(e: React.FormEvent) {
    e.preventDefault();
    if (!puedeBuscar) return;
    setBuscando(true);
    setErrorBusqueda(null);
    setResultado(null);
    setSeleccion(new Set());
    try {
      const res = await api.prospeccionBuscar({
        condicion: condicion.trim(),
        lat: punto.lat,
        lng: punto.lng,
        radio_m: radio,
      });
      setResultado(res.resultados);
    } catch (err) {
      setErrorBusqueda((err as Error).message);
    } finally {
      setBuscando(false);
    }
  }

  const seleccionables = useMemo(
    () => (resultado ?? []).filter((n) => !n.ya_registrado),
    [resultado],
  );
  const yaRegistrados = (resultado ?? []).length - seleccionables.length;
  const todosMarcados = seleccionables.length > 0 && seleccion.size === seleccionables.length;

  function toggleUno(id: string) {
    setSeleccion((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleTodos() {
    setSeleccion(todosMarcados ? new Set() : new Set(seleccionables.map((n) => n.id)));
  }

  async function cargar() {
    const elegidos = (resultado ?? []).filter((n) => seleccion.has(n.id));
    if (elegidos.length === 0 || cargando) return;
    setCargando(true);
    try {
      const res = await api.prospeccionImportar(
        elegidos.map(({ id, nombre, razon_social, actividad, telefono, correo, direccion }) => ({
          id,
          nombre,
          razon_social,
          actividad,
          telefono,
          correo,
          direccion,
        })),
      );
      const partes = [
        res.importados === 1
          ? "1 prospecto cargado a tu cartera"
          : `${res.importados} prospectos cargados a tu cartera`,
      ];
      if (res.ya_existian > 0)
        partes.push(
          res.ya_existian === 1
            ? "1 ya estaba (no se duplicó)"
            : `${res.ya_existian} ya estaban (no se duplicaron)`,
        );
      toast(partes.join(" · "), "success");
      // Los cargados quedan marcados como "en tu cartera", con liga a su ficha.
      const porId = new Map(res.detalle.map((d) => [d.id, d.cliente_id]));
      setResultado((rs) =>
        (rs ?? []).map((n) =>
          porId.has(n.id) ? { ...n, ya_registrado: true, cliente_id: porId.get(n.id)! } : n,
        ),
      );
      setSeleccion(new Set());
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setCargando(false);
    }
  }

  if (fuente.error) return <ErrorState message={fuente.error} retry={fuente.refetch} />;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Buscar negocios"
        subtitle="Prospección sobre el DENUE del INEGI: el directorio público de los negocios de México. Buscas en vivo, previsualizas y cargas solo los que elijas."
      />

      {fuente.loading && <Skeleton className="h-32 w-full" />}

      {!fuente.loading && fuente.data && !fuente.data.conectada && (
        <EmptyState
          title="Conecta el DENUE del INEGI para prospectar"
          action={
            <Link
              href="/integraciones/detalle?key=denue"
              className="inline-flex rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-surface transition-colors hover:bg-accent-strong"
            >
              Conectar DENUE · INEGI
            </Link>
          }
        >
          El DENUE es el directorio público del INEGI (5.5 millones de negocios). El token es
          gratuito: pídelo en inegi.org.mx, guárdalo en Integraciones y aquí se busca en vivo.
        </EmptyState>
      )}

      {!fuente.loading && fuente.data?.conectada && (
        <>
          <form onSubmit={buscar} className="rounded-lg border border-line bg-surface p-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[220px] flex-1">
                <label htmlFor="p-giro" className="text-[11px] uppercase tracking-[0.06em] text-ink-3">
                  Giro o palabra clave
                </label>
                <input
                  id="p-giro"
                  className={`mt-1 ${inputCls}`}
                  placeholder={'ferreterias, tortillerias, consultorio dental… o "todos"'}
                  value={condicion}
                  onChange={(e) => setCondicion(e.target.value)}
                />
              </div>
              <div className="w-48">
                <label htmlFor="p-zona" className="text-[11px] uppercase tracking-[0.06em] text-ink-3">
                  Zona
                </label>
                <select
                  id="p-zona"
                  className={`mt-1 ${inputCls}`}
                  value={zona}
                  onChange={(e) => setZona(e.target.value)}
                >
                  {ZONAS.map((z) => (
                    <option key={z.key} value={z.key}>
                      {z.label}
                    </option>
                  ))}
                  <option value="propias">Coordenadas propias</option>
                </select>
              </div>
              {zona === "propias" && (
                <>
                  <div className="w-28">
                    <label htmlFor="p-lat" className="text-[11px] uppercase tracking-[0.06em] text-ink-3">
                      Latitud
                    </label>
                    <input
                      id="p-lat"
                      className={`mt-1 ${inputCls}`}
                      placeholder="25.6866"
                      inputMode="decimal"
                      value={latProp}
                      onChange={(e) => setLatProp(e.target.value)}
                    />
                  </div>
                  <div className="w-28">
                    <label htmlFor="p-lng" className="text-[11px] uppercase tracking-[0.06em] text-ink-3">
                      Longitud
                    </label>
                    <input
                      id="p-lng"
                      className={`mt-1 ${inputCls}`}
                      placeholder="-100.3161"
                      inputMode="decimal"
                      value={lngProp}
                      onChange={(e) => setLngProp(e.target.value)}
                    />
                  </div>
                </>
              )}
              <div className="w-44">
                <label htmlFor="p-radio" className="text-[11px] uppercase tracking-[0.06em] text-ink-3">
                  Radio
                </label>
                <select
                  id="p-radio"
                  className={`mt-1 ${inputCls}`}
                  value={radio}
                  onChange={(e) => setRadio(Number(e.target.value))}
                >
                  {RADIOS.map((r) => (
                    <option key={r.m} value={r.m}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>
              <PrimaryButton type="submit" disabled={!puedeBuscar}>
                {buscando ? "Buscando…" : "Buscar negocios"}
              </PrimaryButton>
            </div>
            <p className="mt-2.5 text-[11.5px] text-ink-3">
              Búsqueda en vivo alrededor del punto elegido (así funciona la API pública del
              INEGI). Nada se guarda hasta que tú cargues.
            </p>
          </form>

          <div className="mt-4">
            {buscando && (
              <div className="space-y-2">
                <Skeleton className="h-11 w-full rounded-lg" />
                <Skeleton className="h-11 w-full rounded-lg" />
                <Skeleton className="h-11 w-full rounded-lg" />
              </div>
            )}

            {!buscando && errorBusqueda && (
              <div className="reveal rounded-lg border border-line bg-danger-soft px-4 py-3">
                <p className="text-[12.5px] font-medium text-danger">La fuente no respondió</p>
                <p className="mt-0.5 text-[12.5px] text-danger">{errorBusqueda}</p>
              </div>
            )}

            {!buscando && !errorBusqueda && resultado === null && (
              <EmptyState title="Busca negocios reales para prospectar">
                Elige un giro y una zona: verás nombre, giro, dirección y contacto de cada
                negocio del directorio público. Cargas solo los que marques.
              </EmptyState>
            )}

            {!buscando && !errorBusqueda && resultado !== null && resultado.length === 0 && (
              <EmptyState title="Sin resultados en esa zona">
                El INEGI no encontró negocios con esa palabra ahí. Prueba el giro en plural y
                sin acentos (así indexa el DENUE: &quot;ferreterias&quot;, &quot;tortillerias&quot;), amplía el
                radio o cambia de zona.
              </EmptyState>
            )}

            {!buscando && !errorBusqueda && resultado !== null && resultado.length > 0 && (
              <>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <p className="text-[12.5px] text-ink-2">
                    <span className="tnum font-medium text-ink">{resultado.length}</span>{" "}
                    negocios · fuente DENUE · INEGI
                    {yaRegistrados > 0 && (
                      <span className="text-ink-3"> · {yaRegistrados} ya en tu cartera</span>
                    )}
                  </p>
                  <PrimaryButton onClick={cargar} disabled={seleccion.size === 0 || cargando}>
                    {cargando
                      ? "Cargando…"
                      : seleccion.size > 0
                        ? `Cargar ${seleccion.size} a prospectos`
                        : "Cargar a prospectos"}
                  </PrimaryButton>
                </div>

                <div className="reveal overflow-x-auto rounded-lg border border-line bg-surface">
                  <table className="w-full min-w-[820px] text-left">
                    <thead>
                      <tr className="border-b border-line bg-panel/60 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                        <th className="w-10 px-4 py-2.5">
                          <input
                            type="checkbox"
                            className="accent-accent"
                            checked={todosMarcados}
                            disabled={seleccionables.length === 0}
                            onChange={toggleTodos}
                            aria-label="Seleccionar todos los que no están en tu cartera"
                          />
                        </th>
                        <th className="px-4 py-2.5">Negocio</th>
                        <th className="px-4 py-2.5">Giro</th>
                        <th className="px-4 py-2.5">Dirección</th>
                        <th className="px-4 py-2.5">Contacto</th>
                        <th className="px-4 py-2.5">Cartera</th>
                      </tr>
                    </thead>
                    <tbody>
                      {resultado.map((n) => (
                        <tr
                          key={n.id}
                          onClick={() => !n.ya_registrado && toggleUno(n.id)}
                          className={`border-b border-line/60 transition-colors last:border-0 ${
                            n.ya_registrado ? "bg-panel/30" : "cursor-pointer hover:bg-panel/40"
                          }`}
                        >
                          <td className="px-4 py-2.5">
                            {n.ya_registrado ? (
                              <svg viewBox="0 0 12 12" className="h-3 w-3 text-ok" fill="none" aria-label="Ya en tu cartera">
                                <path d="m2.5 6.5 2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            ) : (
                              <input
                                type="checkbox"
                                className="accent-accent"
                                checked={seleccion.has(n.id)}
                                onChange={() => toggleUno(n.id)}
                                onClick={(e) => e.stopPropagation()}
                                aria-label={`Seleccionar ${n.nombre}`}
                              />
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            <span className="block text-[12.5px] font-medium text-ink">{n.nombre}</span>
                            {n.razon_social && n.razon_social !== n.nombre && (
                              <span className="block text-[11.5px] text-ink-3">{n.razon_social}</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-[12px] text-ink-2">
                            {n.actividad || <span className="text-ink-3">·</span>}
                          </td>
                          <td className="max-w-[240px] px-4 py-2.5 text-[12px] text-ink-2">
                            {n.direccion || <span className="text-ink-3">·</span>}
                          </td>
                          <td className="px-4 py-2.5 text-[12px] text-ink-2">
                            {n.telefono ? (
                              <span className="tnum block">{n.telefono}</span>
                            ) : null}
                            {n.correo ? (
                              <span className="block truncate lowercase">{n.correo}</span>
                            ) : null}
                            {!n.telefono && !n.correo && (
                              <span className="text-ink-3">sin contacto</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-[12px]">
                            {n.ya_registrado && n.cliente_id ? (
                              <Link
                                href={`/clientes/detalle?id=${n.cliente_id}`}
                                onClick={(e) => e.stopPropagation()}
                                className="font-medium text-accent-ink underline-offset-2 hover:underline"
                              >
                                Ya está · ver ficha
                              </Link>
                            ) : (
                              <span className="text-ink-3">nuevo</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
