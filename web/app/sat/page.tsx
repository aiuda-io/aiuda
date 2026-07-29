"use client";

import { type FormEvent, useRef, useState } from "react";
import Link from "next/link";
import { api, mxn, type SatImportResult } from "@/lib/api";
import { fecha } from "@/lib/format";
import {
  ErrorState,
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

const RFC_RE = /^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$/;

function numero(value: FormDataEntryValue | null, fallback = 30) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function estadoSync(ultima: string | null, pendiente: boolean) {
  if (pendiente) return "Solicitud pendiente";
  if (ultima) return `Al día hasta ${fecha(ultima)}`;
  return "Aún no sincroniza";
}

export default function SatPage() {
  const estadoApi = useApi(api.satEstado);
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
    await Promise.all([estadoApi.refetch(), bovedaApi.refetch()]);
  }

  async function guardarEmpresa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const rfc = String(data.get("rfc") ?? "").trim().toUpperCase();
    if (!RFC_RE.test(rfc)) {
      toast("Revisa el RFC.", "error");
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
      toast((error as Error).message, "error");
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
      toast("e.firma validada y guardada cifrada.", "info");
      await refrescar();
    } catch (error) {
      toast((error as Error).message, "error");
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
      toast(`${res.nuevos} CFDI nuevos; ${res.duplicados} ya estaban.`, "info");
      await refrescar();
    } catch (error) {
      toast((error as Error).message, "error");
    } finally {
      setBusy("");
    }
  }

  async function cambiarPlazo(rfc: string, value: string) {
    setBusy(`plazo:${rfc}`);
    try {
      await api.satCambiarEmpresa(rfc, { plazo_dias: numero(value) });
      toast("Plazo actualizado. Aplica a CFDI nuevos.", "info");
      await estadoApi.refetch();
    } catch (error) {
      toast((error as Error).message, "error");
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
      toast((error as Error).message, "error");
    } finally {
      setBusy("");
    }
  }

  async function borrar(rfc: string, efirma: boolean) {
    const ok = await confirm({
      title: efirma ? "Borrar e.firma" : "Quitar empresa",
      message: efirma
        ? `Se borrará la credencial cifrada de ${rfc}. Los CFDI importados se conservan.`
        : `Se quitará ${rfc}. Los CFDI importados se conservan.`,
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
      toast((error as Error).message, "error");
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
        title="SAT · Bóveda fiscal"
        subtitle="Tus CFDI en esta computadora. Hasta 3 RFCs; la e.firma nunca sale por la API."
        right={
          <Link
            href="/manual/sat.html"
            className="text-cuerpo font-medium text-accent-ink hover:underline"
          >
            Ver manual
          </Link>
        }
      />

      {estadoApi.error && <ErrorState message={estadoApi.error} retry={estadoApi.refetch} />}
      {estadoApi.loading && !estado && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-20 rounded-lg" />
          ))}
        </div>
      )}

      {estado && (
        <div className="mb-7 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            ["Empresas", `${empresas.length} / ${estado.maximo}`],
            ["CFDI", String(estado.boveda.total)],
            ["Intercompañía", String(estado.boveda.intercompania)],
            ["Cartera abierta", mxn(estado.cartera.todo_junto.total)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-line bg-surface px-4 py-3.5">
              <p className="text-apoyo text-ink-2">{label}</p>
              <p className="hero-num mt-1 text-titulo font-semibold text-ink">{value}</p>
            </div>
          ))}
        </div>
      )}

      <SettingsSection
        title="Tus empresas"
        desc="Registra un RFC para clasificar XML. Con e.firma también puede entrar a Descarga Masiva."
      >
        <div className="space-y-3">
          {empresas.map((empresa) => (
            <article key={empresa.rfc} className="rounded-lg border border-line bg-surface p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-seccion font-semibold text-ink">{empresa.rfc}</p>
                  <p className="mt-0.5 text-apoyo text-ink-3">
                    {empresa.nombre || "Sin razón social"} ·{" "}
                    {empresa.efirma ? `e.firma vigente hasta ${fecha(empresa.vigente_hasta)}` : "Carga manual"}
                  </p>
                </div>
                <div className="flex gap-3 text-apoyo">
                  {empresa.efirma && (
                    <button
                      onClick={() => probar(empresa.rfc)}
                      disabled={Boolean(busy)}
                      className="font-medium text-accent-ink disabled:opacity-50"
                    >
                      {busy === `probar:${empresa.rfc}` ? "Probando…" : "Probar con SAT"}
                    </button>
                  )}
                  <button
                    onClick={() => borrar(empresa.rfc, empresa.efirma)}
                    disabled={Boolean(busy)}
                    className="text-ink-3 hover:text-danger disabled:opacity-50"
                  >
                    {busy === `borrar:${empresa.rfc}` ? "Borrando…" : "Borrar"}
                  </button>
                </div>
              </div>
              <div className="mt-3 grid gap-3 border-t border-line pt-3 sm:grid-cols-[8rem_1fr_1fr]">
                <label className="text-apoyo text-ink-3">
                  Plazo PPD estimado
                  <select
                    value={empresa.plazo_dias}
                    disabled={Boolean(busy)}
                    onChange={(event) => cambiarPlazo(empresa.rfc, event.target.value)}
                    className={`${inputCls} mt-1 py-1.5`}
                  >
                    {[15, 30, 45, 60, 90].map((dias) => (
                      <option key={dias} value={dias}>{dias} días</option>
                    ))}
                  </select>
                </label>
                {(["emitidas", "recibidas"] as const).map((scope) => (
                  <div key={scope} className="text-apoyo">
                    <p className="font-medium capitalize text-ink">{scope}</p>
                    <p className="mt-1 text-ink-3">
                      {estadoSync(
                        empresa.sync[scope].ultima_fecha,
                        empresa.sync[scope].solicitud_pendiente,
                      )}
                    </p>
                  </div>
                ))}
              </div>
            </article>
          ))}

          {empresas.length < (estado?.maximo ?? 3) && (
            <form onSubmit={guardarEmpresa} className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,8rem)_auto]">
              <input
                name="rfc"
                required
                maxLength={13}
                placeholder="RFC"
                autoCapitalize="characters"
                className={inputCls}
              />
              <input name="nombre" placeholder="Razón social (opcional)" className={inputCls} />
              <select name="plazo_dias" defaultValue="30" className={inputCls}>
                {[15, 30, 45, 60, 90].map((dias) => (
                  <option key={dias} value={dias}>{dias} días</option>
                ))}
              </select>
              <SecondaryButton disabled={Boolean(busy)}>
                {busy === "empresa" ? "Guardando…" : "Agregar"}
              </SecondaryButton>
            </form>
          )}
        </div>
      </SettingsSection>

      <SettingsSection
        title="Conectar e.firma"
        desc="Se valida antes de guardar. También puedes convertir una empresa registrada manualmente, aunque ya hayas ocupado los 3 espacios."
      >
          <form ref={efirmaForm} onSubmit={conectarEfirma} className="space-y-4" autoComplete="off">
            <div className="grid gap-3 sm:grid-cols-2">
              <SettingsField label="Certificado .cer">
                <input name="cer" type="file" accept=".cer" required className={inputCls} />
              </SettingsField>
              <SettingsField label="Llave privada .key">
                <input name="key" type="file" accept=".key" required className={inputCls} />
              </SettingsField>
            </div>
            <div className="grid gap-3 sm:grid-cols-[1fr_8rem]">
              <SettingsField label="Contraseña">
                <input
                  name="password"
                  type="password"
                  required
                  autoComplete="new-password"
                  className={inputCls}
                />
              </SettingsField>
              <SettingsField label="Plazo PPD">
                <select name="plazo_dias" defaultValue="30" className={inputCls}>
                  {[15, 30, 45, 60, 90].map((dias) => (
                    <option key={dias} value={dias}>{dias} días</option>
                  ))}
                </select>
              </SettingsField>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="max-w-md text-apoyo leading-relaxed text-ink-3">
                Los archivos y la contraseña se cifran juntos. La consola solo vuelve a mostrar RFC,
                titular y vigencia.
              </p>
              <PrimaryButton disabled={Boolean(busy)}>
                {busy === "efirma" ? "Validando…" : "Validar y conectar"}
              </PrimaryButton>
            </div>
          </form>
      </SettingsSection>

      <SettingsSection
        title="Importar XML o ZIP"
        desc="Carga manual inmediata. UUID repetidos no duplican; intercompañía queda fuera de cartera."
      >
        <form ref={importForm} onSubmit={importar} className="space-y-3">
          <input
            name="archivo"
            type="file"
            accept=".xml,.zip,application/xml,application/zip"
            required
            className={inputCls}
          />
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-52 flex-1 text-apoyo text-ink-3">
              Registrar o clasificar como
              <select name="rfc" defaultValue="" className={`${inputCls} mt-1`}>
                <option value="">Detectar con empresas registradas</option>
                {empresas.map((empresa) => (
                  <option key={empresa.rfc} value={empresa.rfc}>{empresa.rfc}</option>
                ))}
              </select>
            </label>
            <PrimaryButton disabled={Boolean(busy)}>
              {busy === "importar" ? "Importando…" : "Importar"}
            </PrimaryButton>
          </div>
        </form>
        {resultado && (
          <div className="mt-3 rounded-lg border border-line bg-panel/30 px-4 py-3 text-apoyo text-ink-2">
            {resultado.nuevos} nuevos · {resultado.duplicados} duplicados ·{" "}
            {resultado.facturas_creadas} cuentas por cobrar
            {resultado.avisos.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-4 text-warn">
                {resultado.avisos.map((aviso) => <li key={aviso}>{aviso}</li>)}
              </ul>
            )}
          </div>
        )}
      </SettingsSection>

      <SettingsSection
        title="Bóveda"
        desc="Hasta 2,000 CFDI recientes. El XML completo no sale en este listado."
      >
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <select value={rfcFiltro} onChange={(event) => setRfcFiltro(event.target.value)} className={inputCls}>
              <option value="">Todos los RFCs</option>
              {empresas.map((empresa) => (
                <option key={empresa.rfc} value={empresa.rfc}>{empresa.rfc}</option>
              ))}
            </select>
            <select value={direccion} onChange={(event) => setDireccion(event.target.value)} className={inputCls}>
              <option value="">Todas las direcciones</option>
              <option value="emitida">Emitidas</option>
              <option value="recibida">Recibidas</option>
              <option value="intercompania">Intercompañía</option>
              <option value="desconocida">Sin clasificar</option>
            </select>
          </div>
          {bovedaApi.error && <ErrorState message={bovedaApi.error} retry={bovedaApi.refetch} />}
          {bovedaApi.loading && !boveda && <Skeleton className="h-40 rounded-lg" />}
          {boveda && (
            <div className="overflow-x-auto rounded-lg border border-line bg-surface">
              <table className="w-full min-w-[680px] text-left text-apoyo">
                <thead className="border-b border-line bg-panel/30 text-ink-3">
                  <tr>
                    <th className="px-3 py-2 font-medium">Fecha</th>
                    <th className="px-3 py-2 font-medium">Folio</th>
                    <th className="px-3 py-2 font-medium">Emisor</th>
                    <th className="px-3 py-2 font-medium">Receptor</th>
                    <th className="px-3 py-2 text-right font-medium">Total</th>
                    <th className="px-3 py-2 font-medium">Clase</th>
                  </tr>
                </thead>
                <tbody>
                  {boveda.cfdis.map((cfdi) => (
                    <tr key={cfdi.uuid} className="border-b border-line last:border-b-0">
                      <td className="whitespace-nowrap px-3 py-2.5 text-ink-3">{fecha(cfdi.fecha)}</td>
                      <td className="px-3 py-2.5 font-medium text-ink">{cfdi.folio || cfdi.uuid.slice(0, 8)}</td>
                      <td className="max-w-40 truncate px-3 py-2.5 text-ink-2">{cfdi.nombre_emisor || cfdi.rfc_emisor}</td>
                      <td className="max-w-40 truncate px-3 py-2.5 text-ink-2">{cfdi.nombre_receptor || cfdi.rfc_receptor}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right text-ink">{mxn(cfdi.total ?? 0)}</td>
                      <td className="px-3 py-2.5 capitalize text-ink-3">{cfdi.direccion}</td>
                    </tr>
                  ))}
                  {boveda.cfdis.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-10 text-center text-ink-3">
                        Aún no hay CFDI con estos filtros.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </SettingsSection>
      {dialog}
    </SettingsPage>
  );
}
