"use client";

import { type FormEvent, useRef, useState } from "react";
import Link from "next/link";
import { api, apiUrl, type SatImportResult } from "@/lib/api";
import { fecha, fechaHora } from "@/lib/format";
import {
  ErrorState,
  FilePicker,
  PageHeader,
  PrimaryButton,
  SecondaryButton,
  Skeleton,
  inputCls,
  useApi,
  useConfirm,
} from "@/components/ui";
import { SettingsField, SettingsPage, SettingsSection } from "@/components/settings";
import { toast } from "@/components/toast";
import { dinero, leerFallo, plural, RUTA } from "@/lib/cartera";

const RFC_RE = /^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$/;

function numero(value: FormDataEntryValue | null, fallback = 30) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

// La vigencia viene como día (AAAA-MM-DD): vencida desde el día siguiente, en hora local.
function efirmaVencida(vigenteHasta: string | null) {
  if (!vigenteHasta) return false;
  const ahora = new Date();
  const hoy = `${ahora.getFullYear()}-${String(ahora.getMonth() + 1).padStart(2, "0")}-${String(
    ahora.getDate(),
  ).padStart(2, "0")}`;
  return vigenteHasta.slice(0, 10) < hoy;
}

function estadoSync(ultima: string | null, pendiente: boolean) {
  if (pendiente) return "Esperando la respuesta del SAT";
  if (ultima) return `Al día hasta el ${fecha(ultima)}`;
  return "Todavía no se ha traído nada";
}

const SENTIDO = { emitidas: "Las que emites", recibidas: "Las que recibes" } as const;

const TIPO_CFDI: Record<string, string> = {
  emitida: "Emitida",
  recibida: "Recibida",
  intercompania: "Entre tus empresas",
  desconocida: "Sin clasificar",
};

const DIAS_CREDITO = [15, 30, 45, 60, 90];

// Una sola rejilla para el encabezado y los renglones de los CFDI guardados.
const COLUMNAS_CFDI = "lg:grid-cols-[6.5rem_8rem_minmax(0,1fr)_minmax(0,1fr)_9rem_9rem]";

export default function SatPage() {
  const estadoApi = useApi(api.satEstado);
  const documentosApi = useApi(api.cuaDeterministas);
  const [rfcFiltro, setRfcFiltro] = useState("");
  const [direccion, setDireccion] = useState("");
  const bovedaApi = useApi(
    () => api.satBoveda({ rfc: rfcFiltro, direccion }),
    [rfcFiltro, direccion],
  );
  const [busy, setBusy] = useState("");
  const [resultado, setResultado] = useState<SatImportResult | null>(null);
  const efirmaForm = useRef<HTMLFormElement>(null);
  const importForm = useRef<HTMLFormElement>(null);
  const { confirm, dialog } = useConfirm();

  async function refrescar() {
    await Promise.all([estadoApi.refetch(), bovedaApi.refetch(), documentosApi.refetch()]);
  }

  async function guardarEmpresa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const rfc = String(data.get("rfc") ?? "").trim().toUpperCase();
    if (!RFC_RE.test(rfc)) {
      toast("Ese RFC no se ve bien. Revísalo.", "error");
      return;
    }
    setBusy("empresa");
    try {
      await api.satAgregarEmpresa({
        rfc,
        nombre: String(data.get("nombre") ?? "").trim(),
        plazo_dias: numero(data.get("plazo_dias")),
      });
      form.reset();
      toast("Empresa registrada.", "info");
      await refrescar();
    } catch (error) {
      toast(leerFallo(error).mensaje, "error");
    } finally {
      setBusy("");
    }
  }

  async function conectarEfirma(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy("efirma");
    try {
      await api.satConectarEfirma(data);
      form.reset();
      toast("e.firma validada. Quedó guardada y cifrada en esta computadora.", "success");
      await refrescar();
    } catch (error) {
      toast(leerFallo(error).mensaje, "error");
    } finally {
      data.delete("password");
      setBusy("");
    }
  }

  async function importar(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy("importar");
    try {
      const res = await api.satImportar(new FormData(form));
      setResultado(res);
      form.reset();
      toast(`${plural(res.nuevos, "CFDI nuevo", "CFDI nuevos")}. ${plural(res.duplicados, "ya estaba", "ya estaban")}.`, "info");
      await refrescar();
    } catch (error) {
      toast(leerFallo(error).mensaje, "error");
    } finally {
      setBusy("");
    }
  }

  async function cambiarPlazo(rfc: string, value: string) {
    setBusy(`plazo:${rfc}`);
    try {
      await api.satCambiarEmpresa(rfc, { plazo_dias: numero(value) });
      toast("Días de crédito actualizados. Aplican a las facturas que lleguen de ahora en adelante.", "info");
      await estadoApi.refetch();
    } catch (error) {
      toast(leerFallo(error).mensaje, "error");
    } finally {
      setBusy("");
    }
  }

  async function probar(rfc: string) {
    setBusy(`probar:${rfc}`);
    try {
      const res = await api.satProbarEfirma(rfc);
      toast(res.mensaje, "info");
      await estadoApi.refetch();
    } catch (error) {
      toast(leerFallo(error).mensaje, "error");
    } finally {
      setBusy("");
    }
  }

  async function borrar(rfc: string, efirma: boolean) {
    const ok = await confirm({
      title: efirma ? "Borrar e.firma" : "Quitar empresa",
      message: efirma
        ? `Se borrará la e.firma guardada de ${rfc}. Los CFDI que ya tienes se conservan.`
        : `Se quitará ${rfc}. Los CFDI que ya tienes se conservan.`,
      confirmLabel: "Borrar",
    });
    if (!ok) return;
    setBusy(`borrar:${rfc}`);
    try {
      if (efirma) await api.satBorrarEfirma(rfc);
      else await api.satQuitarEmpresa(rfc);
      toast(efirma ? "e.firma borrada." : "Empresa quitada.", "info");
      if (rfcFiltro === rfc) setRfcFiltro("");
      await refrescar();
    } catch (error) {
      toast(leerFallo(error).mensaje, "error");
    } finally {
      setBusy("");
    }
  }

  const estado = estadoApi.data;
  const empresas = estado?.empresas ?? [];
  const boveda = bovedaApi.data;

  return (
    <SettingsPage>
      <PageHeader
        title="Traer del SAT"
        subtitle="Tus facturas (CFDI) tal como las tiene el SAT, guardadas en esta computadora. Las que te deben entran solas a tu cartera."
        right={
          <a href="/manual/sat.html" className="btn btn-quiet">
            Ver el manual
          </a>
        }
      />

      {estadoApi.error && <ErrorState message={estadoApi.error} retry={estadoApi.refetch} />}
      {estadoApi.loading && !estado && <Skeleton className="mb-10 h-16 w-full max-w-xl" />}

      {estado && (
        <dl className="mb-10 flex flex-wrap gap-x-12 gap-y-5">
          {[
            ["Empresas", `${empresas.length} de ${estado.maximo}`],
            ["CFDI guardados", String(estado.boveda.total)],
            ["Entre tus empresas", String(estado.boveda.intercompania)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-rotulo text-ink-3">{label}</dt>
              <dd className="hero-num mt-1 text-titulo text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      <SettingsSection
        title="Tus empresas"
        desc="Registra el RFC de cada empresa para saber qué facturas emites y cuáles recibes. Con su e.firma, aiuda las trae sola del SAT."
      >
        <div className="space-y-4">
          {empresas.map((empresa) => (
            <article key={empresa.rfc} className="rounded-2xl bg-panel p-5">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
                <div className="min-w-0">
                  <p className="tnum text-seccion font-semibold text-ink">{empresa.rfc}</p>
                  <p className="mt-0.5 text-apoyo text-ink-2">{empresa.nombre || "Sin razón social"}</p>
                  <p
                    className="mark mt-2"
                    style={
                      {
                        "--mark": !empresa.efirma
                          ? "var(--color-ink-3)"
                          : efirmaVencida(empresa.vigente_hasta)
                            ? "var(--color-danger)"
                            : "var(--color-ok)",
                        whiteSpace: "normal",
                      } as React.CSSProperties
                    }
                  >
                    {!empresa.efirma
                      ? "Sin e.firma: subes sus archivos a mano"
                      : efirmaVencida(empresa.vigente_hasta)
                        ? `Su e.firma venció el ${fecha(empresa.vigente_hasta)}`
                        : `e.firma vigente hasta el ${fecha(empresa.vigente_hasta)}`}
                  </p>
                </div>
                <div className="flex flex-wrap gap-1">
                  {empresa.efirma && (
                    <button
                      onClick={() => probar(empresa.rfc)}
                      disabled={Boolean(busy)}
                      className="btn btn-sm btn-quiet"
                    >
                      {busy === `probar:${empresa.rfc}` ? "Probando…" : "Probar con el SAT"}
                    </button>
                  )}
                  <button
                    onClick={() => borrar(empresa.rfc, empresa.efirma)}
                    disabled={Boolean(busy)}
                    className="btn btn-sm btn-quiet"
                  >
                    {busy === `borrar:${empresa.rfc}`
                      ? "Borrando…"
                      : empresa.efirma
                        ? "Borrar e.firma"
                        : "Quitar"}
                  </button>
                </div>
              </div>
              <div className="mt-5 grid gap-x-6 gap-y-4 sm:grid-cols-3">
                <label className="text-apoyo text-ink-2">
                  Días de crédito que das
                  <select
                    value={empresa.plazo_dias}
                    disabled={Boolean(busy)}
                    onChange={(event) => cambiarPlazo(empresa.rfc, event.target.value)}
                    className={`${inputCls} mt-1`}
                  >
                    {DIAS_CREDITO.map((dias) => (
                      <option key={dias} value={dias}>{dias} días</option>
                    ))}
                  </select>
                </label>
                {(["emitidas", "recibidas"] as const).map((scope) => (
                  <div key={scope} className="text-apoyo">
                    <p className="text-ink-2">{SENTIDO[scope]}</p>
                    <p className="mt-1 text-cuerpo text-ink">
                      {estadoSync(
                        empresa.sync[scope].ultima_fecha,
                        empresa.sync[scope].solicitud_pendiente,
                      )}
                    </p>
                    {empresa.sync[scope].aviso && (
                      <p className="mt-1 text-ink-3">{empresa.sync[scope].aviso}</p>
                    )}
                    {empresa.sync[scope].cancelaciones_hasta && (
                      <p className="mt-1 text-ink-3">
                        Cancelaciones revisadas al {fecha(empresa.sync[scope].cancelaciones_hasta)}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </article>
          ))}

          {empresas.length < (estado?.maximo ?? 3) && (
            <form
              onSubmit={guardarEmpresa}
              className="grid gap-2 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_minmax(0,8rem)_auto]"
            >
              <input
                name="rfc"
                required
                maxLength={13}
                placeholder="RFC"
                aria-label="RFC de la empresa"
                autoCapitalize="characters"
                className={inputCls}
              />
              <input
                name="nombre"
                placeholder="Razón social (opcional)"
                aria-label="Razón social"
                className={inputCls}
              />
              <select name="plazo_dias" defaultValue="30" aria-label="Días de crédito que das" className={inputCls}>
                {DIAS_CREDITO.map((dias) => (
                  <option key={dias} value={dias}>{dias} días</option>
                ))}
              </select>
              <SecondaryButton disabled={Boolean(busy)}>
                {busy === "empresa" ? "Guardando…" : "Agregar empresa"}
              </SecondaryButton>
            </form>
          )}
        </div>
      </SettingsSection>

      <SettingsSection
        title="Subir XML o ZIP"
        desc="Los archivos que bajaste del portal del SAT. Lo repetido no se duplica, y las facturas entre tus propias empresas no cuentan como cartera."
      >
        <form ref={importForm} onSubmit={importar} className="space-y-4">
          <FilePicker
            name="archivo"
            accept=".xml,.zip,application/xml,application/zip"
            required
            hint="Un XML, o el ZIP con varios"
          />
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-52 flex-1 text-apoyo text-ink-2">
              De qué empresa son
              <select name="rfc" defaultValue="" className={`${inputCls} mt-1`}>
                <option value="">Que aiuda lo reconozca</option>
                {empresas.map((empresa) => (
                  <option key={empresa.rfc} value={empresa.rfc}>{empresa.rfc}</option>
                ))}
              </select>
            </label>
            <PrimaryButton disabled={Boolean(busy)}>
              {busy === "importar" ? "Subiendo…" : "Subir"}
            </PrimaryButton>
          </div>
        </form>
        {resultado && (
          <div className="mt-5">
            <p
              className="mark text-cuerpo text-ink"
              style={{ "--mark": "var(--color-ok)", whiteSpace: "normal" } as React.CSSProperties}
            >
              {plural(resultado.nuevos, "CFDI nuevo", "CFDI nuevos")},{" "}
              {plural(resultado.duplicados, "ya estaba", "ya estaban")}
            </p>
            <p className="mt-1 text-cuerpo text-ink-2">
              {resultado.facturas_creadas > 0 ? (
                <>
                  {plural(resultado.facturas_creadas, "factura por cobrar entró", "facturas por cobrar entraron")}{" "}
                  a tu{" "}
                  <Link href={RUTA.cartera} className="font-medium text-accent-ink hover:underline">
                    Cartera
                  </Link>
                  .
                </>
              ) : (
                "Ninguna factura nueva por cobrar."
              )}
            </p>
            {resultado.avisos.map((aviso) => (
              <p key={aviso} className="mt-2 text-apoyo text-ink-2">
                {aviso}
              </p>
            ))}
          </div>
        )}
      </SettingsSection>

      <SettingsSection
        title="Conectar tu e.firma"
        desc="Con ella aiuda trae tus CFDI del SAT sin que subas archivos. Se valida antes de guardarse y queda cifrada en esta computadora."
      >
        <form ref={efirmaForm} onSubmit={conectarEfirma} className="space-y-4" autoComplete="off">
          <div className="grid gap-4 sm:grid-cols-2">
            <SettingsField label="Certificado">
              <FilePicker name="cer" accept=".cer" required hint="Termina en .cer" />
            </SettingsField>
            <SettingsField label="Llave privada">
              <FilePicker name="key" accept=".key" required hint="Termina en .key" />
            </SettingsField>
          </div>
          <div className="grid gap-4 sm:grid-cols-[1fr_10rem]">
            <SettingsField label="Contraseña de la e.firma">
              <input
                name="password"
                type="password"
                required
                autoComplete="new-password"
                className={inputCls}
              />
            </SettingsField>
            <SettingsField label="Días de crédito">
              <select name="plazo_dias" defaultValue="30" className={inputCls}>
                {DIAS_CREDITO.map((dias) => (
                  <option key={dias} value={dias}>{dias} días</option>
                ))}
              </select>
            </SettingsField>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="max-w-md text-apoyo text-ink-2">
              Los dos archivos y la contraseña se cifran juntos. Después, aiuda solo vuelve a
              mostrar el RFC, el titular y la vigencia.
            </p>
            <SecondaryButton disabled={Boolean(busy)}>
              {busy === "efirma" ? "Validando…" : "Validar y conectar"}
            </SecondaryButton>
          </div>
        </form>
      </SettingsSection>

      <SettingsSection
        title="Documentos"
        desc="La opinión de cumplimiento y la constancia de situación fiscal que aiuda bajó del portal del SAT con tu e.firma."
      >
        {documentosApi.error && (
          <ErrorState message={documentosApi.error} retry={documentosApi.refetch} />
        )}
        {documentosApi.loading && !documentosApi.data && <Skeleton className="h-16 w-full" />}
        {documentosApi.data &&
          (documentosApi.data.empresas.length === 0 ? (
            <p className="text-cuerpo text-ink-2">
              Todavía no hay documentos. Conecta una e.firma y aiuda podrá bajarlos por ti.
            </p>
          ) : (
            <div className="space-y-6">
              {documentosApi.data.empresas.map((empresa) => (
                <div key={empresa.rfc}>
                  <p className="tnum text-cuerpo font-semibold text-ink">{empresa.rfc}</p>
                  <ul className="mt-1">
                    {empresa.rutinas.map((rutina) => {
                      const doc = rutina.ultimo_documento;
                      return (
                        <li
                          key={rutina.capacidad}
                          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line py-2.5 last:border-0"
                        >
                          <span className="text-cuerpo text-ink">{rutina.nombre}</span>
                          {doc ? (
                            <span className="flex flex-wrap items-baseline gap-x-3 text-apoyo text-ink-3">
                              {doc.sentido && <span className="text-ink-2">{doc.sentido}</span>}
                              <span className="tnum">{fechaHora(doc.fecha)}</span>
                              <a
                                href={apiUrl(`/v1/documentos/${doc.id}.pdf`)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="font-medium text-accent-ink hover:underline"
                              >
                                Ver PDF
                              </a>
                            </span>
                          ) : (
                            <span className="text-apoyo text-ink-3">Aún no se ha bajado</span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
              <p className="text-apoyo text-ink-2">
                Para bajarlos o actualizarlos ve a{" "}
                <Link href={RUTA.portales} className="font-medium text-accent-ink hover:underline">
                  Portales
                </Link>
                .
              </p>
            </div>
          ))}
      </SettingsSection>

      <SettingsSection title="CFDI guardados" desc="Los 2,000 más recientes de todas tus empresas.">
        <div className="grid gap-2 sm:grid-cols-2">
          <select
            value={rfcFiltro}
            onChange={(event) => setRfcFiltro(event.target.value)}
            aria-label="Empresa"
            className={inputCls}
          >
            <option value="">Todas las empresas</option>
            {empresas.map((empresa) => (
              <option key={empresa.rfc} value={empresa.rfc}>{empresa.rfc}</option>
            ))}
          </select>
          <select
            value={direccion}
            onChange={(event) => setDireccion(event.target.value)}
            aria-label="Tipo de CFDI"
            className={inputCls}
          >
            <option value="">Emitidas y recibidas</option>
            <option value="emitida">Solo emitidas</option>
            <option value="recibida">Solo recibidas</option>
            <option value="intercompania">Entre tus empresas</option>
            <option value="desconocida">Sin clasificar</option>
          </select>
        </div>
        {bovedaApi.error && <ErrorState message={bovedaApi.error} retry={bovedaApi.refetch} />}
        {bovedaApi.loading && !boveda && <Skeleton className="mt-5 h-32 w-full" />}
        {boveda &&
          (boveda.cfdis.length === 0 ? (
            <p className="mt-6 text-cuerpo text-ink-2">
              {rfcFiltro || direccion
                ? "Ningún CFDI coincide con lo que elegiste."
                : "Todavía no hay CFDI guardados. Sube un XML o un ZIP arriba para empezar."}
            </p>
          ) : (
            <>
              <div
                className={`mt-6 hidden gap-x-4 border-b border-line pb-2 text-rotulo font-medium text-ink-3 lg:grid ${COLUMNAS_CFDI}`}
              >
                <span>Fecha</span>
                <span>Folio</span>
                <span>Emisor</span>
                <span>Receptor</span>
                <span className="text-right">Total</span>
                <span>Tipo</span>
              </div>
              <ul className="mt-4 lg:mt-0">
                {boveda.cfdis.map((cfdi) => (
                  <li
                    key={cfdi.uuid}
                    className={`grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-0.5 border-b border-line py-3 text-apoyo last:border-0 lg:items-baseline ${COLUMNAS_CFDI}`}
                  >
                    <span className="tnum order-3 text-ink-3 lg:order-1">{fecha(cfdi.fecha)}</span>
                    <span className="tnum order-1 min-w-0 truncate text-cuerpo font-medium text-ink lg:order-2 lg:text-apoyo">
                      {cfdi.folio || cfdi.uuid.slice(0, 8)}
                    </span>
                    <span className="order-5 col-span-2 truncate text-ink-2 lg:order-3 lg:col-span-1">
                      <span className="lg:hidden">De </span>
                      {cfdi.nombre_emisor || cfdi.rfc_emisor}
                    </span>
                    <span className="order-6 col-span-2 truncate text-ink-2 lg:order-4 lg:col-span-1">
                      <span className="lg:hidden">Para </span>
                      {cfdi.nombre_receptor || cfdi.rfc_receptor}
                    </span>
                    <span className="tnum order-2 whitespace-nowrap text-right text-cuerpo font-semibold text-ink lg:order-5 lg:text-apoyo">
                      {dinero(cfdi.total ?? 0, cfdi.moneda)}
                    </span>
                    <span className="order-4 text-right text-ink-3 lg:order-6 lg:text-left">
                      {cfdi.cancelado ? (
                        <span
                          className="mark"
                          style={{ "--mark": "var(--color-danger)", whiteSpace: "normal" } as React.CSSProperties}
                        >
                          Cancelado{cfdi.cancelado_el ? ` el ${fecha(cfdi.cancelado_el)}` : ""}
                        </span>
                      ) : (
                        (TIPO_CFDI[cfdi.direccion] ?? cfdi.direccion)
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ))}
      </SettingsSection>
      {dialog}
    </SettingsPage>
  );
}
