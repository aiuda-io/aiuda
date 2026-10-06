"use client";

// Builder de conexiones a la medida (conector genérico por API): el fallback abierto cuando aiuda
// no trae un conector nativo. Declaras tu API (URL, auth, paginación, mapeo), la PRUEBAS en vivo
// y la guardas; el motor la lee en cada corrida como una fuente más, con su procedencia. También
// EDITA una conexión guardada: la clave cifrada se conserva si no capturas una nueva.
// Fiel al open-core: una receta declarativa, sin código. Tu clave se cifra en el backend.

import { useEffect, useState, type ReactNode } from "react";
import { PrimaryButton, inputCls } from "@/components/ui";
import { api, type CustomConnector, type CustomTestResult } from "@/lib/api";
import { Drawer } from "@/components/drawer";
import { toast } from "@/components/toast";

export const CAP_LABEL: Record<string, string> = {
  directorio_clientes: "clientes",
  cuentas_por_cobrar: "facturas por cobrar",
  catalogo_productos: "productos",
  agenda: "citas",
  prospeccion: "prospectos",
  expedientes: "expedientes",
};

const FIELD_LABEL: Record<string, string> = {
  name: "Nombre",
  phone: "Teléfono",
  email: "Correo",
  external_id: "ID externo",
  customer: "Cliente",
  folio: "Folio",
  amount: "Monto",
  due_date: "Vence",
  sku: "SKU",
  price: "Precio",
  stock: "Existencia",
  title: "Título",
  starts_at: "Fecha/hora",
};

const AUTH_OPTIONS: { v: string; label: string }[] = [
  { v: "", label: "Sin autenticación" },
  { v: "header", label: "API key en un header" },
  { v: "query", label: "API key en la URL (query param)" },
  { v: "bearer", label: "Clave en el encabezado Authorization (Bearer)" },
  { v: "basic", label: "Usuario y contraseña (Basic)" },
  { v: "oauth2_cc", label: "OAuth2 (client credentials)" },
];

const PAGING_OPTIONS: { v: string; label: string }[] = [
  { v: "", label: "Sin paginación (una sola petición)" },
  { v: "offset", label: "Por corrimiento (offset / limit)" },
  { v: "cursor", label: "Por cursor (la respuesta trae el siguiente)" },
];

function Campo({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-cuerpo font-medium text-ink">{label}</span>
      {hint && <span className="ml-2 text-apoyo text-ink-3">{hint}</span>}
      <div className="mt-1">{children}</div>
    </label>
  );
}

export function CustomConnectorDrawer({
  open,
  onClose,
  cap,
  editar,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  cap: string;
  /** Conexión guardada a editar; null/undefined = crear una nueva. */
  editar?: CustomConnector | null;
  onSaved?: () => void;
}) {
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [listPath, setListPath] = useState("");
  const [root, setRoot] = useState("");
  const [authType, setAuthType] = useState("");
  const [authName, setAuthName] = useState(""); // header o query param
  const [authValue, setAuthValue] = useState("");
  const [tokenUrl, setTokenUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [fields, setFields] = useState<string[]>(["name", "external_id"]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [paging, setPaging] = useState("");
  const [pageParam, setPageParam] = useState("offset");
  const [sizeParam, setSizeParam] = useState("limit");
  const [pageSize, setPageSize] = useState("100");
  const [cursorParam, setCursorParam] = useState("cursor");
  const [cursorPath, setCursorPath] = useState("");
  const [timeout_, setTimeout_] = useState("15");
  const [retries, setRetries] = useState("2");
  const [pauseMs, setPauseMs] = useState("0");
  const [writePath, setWritePath] = useState("");
  const [writeIdPath, setWriteIdPath] = useState("");
  const [avanzado, setAvanzado] = useState(false);
  const [result, setResult] = useState<CustomTestResult | null>(null);
  const [busy, setBusy] = useState<"" | "test" | "save">("");

  const capEfectiva = editar?.cap ?? cap;

  useEffect(() => {
    if (!open) return;
    const e = editar ?? null;
    setName(e?.name ?? "");
    setBaseUrl(e?.base_url ?? "");
    setListPath(e?.list_path ?? "");
    setRoot(e?.root ?? "");
    // Entradas viejas no traen auth_type: header capturado = auth por header (legado).
    setAuthType(e ? (e.auth_type ?? (e.auth_header ? "header" : "")) : "");
    setAuthName(e?.auth_header ?? "");
    setAuthValue(""); // la clave nunca regresa del backend; vacía = se conserva
    setTokenUrl(e?.token_url ?? "");
    setClientId(e?.client_id ?? "");
    setMapping(e?.mapping ?? {});
    setPaging(e?.paging ?? "");
    setPageParam(e?.page_param ?? "offset");
    setSizeParam(e?.size_param ?? "limit");
    setPageSize(String(e?.page_size ?? 100));
    setCursorParam(e?.cursor_param ?? "cursor");
    setCursorPath(e?.cursor_path ?? "");
    setTimeout_(String(e?.timeout ?? 15));
    setRetries(String(e?.retries ?? 2));
    setPauseMs(String(e?.pause_ms ?? 0));
    setWritePath(e?.write_path ?? "");
    setWriteIdPath(e?.write_id_path ?? "");
    setAvanzado(Boolean(e && (e.paging || e.write_path || (e.timeout ?? 15) !== 15 || (e.retries ?? 2) !== 2 || (e.pause_ms ?? 0) !== 0)));
    setResult(null);
    const capParaCampos = e?.cap ?? cap;
    api
      .customConnectorFields()
      .then((f) => setFields(f.cap_fields[capParaCampos] ?? f.default))
      .catch(() => setFields(["name", "external_id"]));
  }, [open, cap, editar]);

  const num = (s: string, fallback: number) => {
    const n = Number(s);
    return Number.isFinite(n) ? Math.trunc(n) : fallback;
  };

  const payload = () => ({
    base_url: baseUrl.trim(),
    list_path: listPath.trim(),
    root: root.trim(),
    auth_type: authType,
    auth_header: authName.trim(),
    auth_value: authValue,
    token_url: tokenUrl.trim(),
    client_id: clientId.trim(),
    mapping: Object.fromEntries(Object.entries(mapping).filter(([, v]) => v.trim())),
    paging,
    page_param: pageParam.trim() || "offset",
    size_param: sizeParam.trim(),
    page_size: num(pageSize, 100),
    cursor_param: cursorParam.trim() || "cursor",
    cursor_path: cursorPath.trim(),
    timeout: num(timeout_, 15),
    retries: num(retries, 2),
    pause_ms: num(pauseMs, 0),
    write_path: writePath.trim(),
    write_id_path: writeIdPath.trim(),
  });

  async function probar() {
    setBusy("test");
    setResult(null);
    try {
      // Al editar sin re-capturar la clave, el backend prueba con la guardada.
      setResult(
        editar
          ? await api.retestCustomConnector(editar.id, payload())
          : await api.testCustomConnector(payload()),
      );
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy("");
    }
  }

  async function guardar() {
    if (!name.trim()) {
      toast("Ponle un nombre a la conexión.", "error");
      return;
    }
    setBusy("save");
    try {
      const body = { ...payload(), name: name.trim(), cap: capEfectiva };
      if (editar) {
        await api.updateCustomConnector(editar.id, body);
        toast("Conexión actualizada.", "info");
      } else {
        await api.createCustomConnector(body);
        toast("Conexión guardada.", "info");
      }
      onSaved?.();
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy("");
    }
  }

  const necesitaNombreAuth = authType === "header" || authType === "query";
  const claveHint =
    editar && editar.has_secret
      ? "vacía = se conserva la guardada"
      : authType === "basic"
        ? "usuario:contraseña"
        : "se cifra";

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={editar ? "Edita tu conexión" : "Crea tu conexión"}
      subtitle={
        editar
          ? `${editar.name} · trae tus ${CAP_LABEL[capEfectiva] ?? "registros"}`
          : `Trae tus ${CAP_LABEL[capEfectiva] ?? "registros"} desde tu propia API`
      }
    >
      <div className="space-y-4">
        <p className="rounded-2xl bg-panel px-5 py-4 text-cuerpo leading-relaxed text-ink-2">
          Esto es para quien conoce la API de tu sistema: se le dice a aiuda su dirección y qué
          campo es cada dato. aiuda la lee cada hora, como a cualquier otra conexión, y anota de
          dónde vino cada registro. Tu clave se guarda cifrada en esta computadora.
        </p>

        <Campo label="Nombre">
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="Mi ERP" />
        </Campo>
        <Campo label="URL base" hint="dónde vive tu API">
          <input className={inputCls} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://miapi.com/api" />
        </Campo>
        <Campo label="Ruta de la lista" hint="se agrega a la URL base (opcional)">
          <input className={inputCls} value={listPath} onChange={(e) => setListPath(e.target.value)} placeholder="clientes" />
        </Campo>

        <Campo label="Autenticación" hint="cómo se identifica aiuda ante tu API">
          <select className={inputCls} value={authType} onChange={(e) => setAuthType(e.target.value)}>
            {AUTH_OPTIONS.map((o) => (
              <option key={o.v} value={o.v}>
                {o.label}
              </option>
            ))}
          </select>
        </Campo>
        {authType === "oauth2_cc" && (
          <div className="grid grid-cols-2 gap-3">
            <Campo label="Dirección donde se pide el acceso" hint="la que da tu API para OAuth2">
              <input className={inputCls} value={tokenUrl} onChange={(e) => setTokenUrl(e.target.value)} placeholder="https://miapi.com/oauth/token" />
            </Campo>
            <Campo label="Client ID">
              <input className={inputCls} value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="mi-app" />
            </Campo>
          </div>
        )}
        {authType !== "" && (
          <div className={necesitaNombreAuth ? "grid grid-cols-2 gap-3" : ""}>
            {necesitaNombreAuth && (
              <Campo label={authType === "query" ? "Nombre del parámetro" : "Nombre del header"}>
                <input
                  className={inputCls}
                  value={authName}
                  onChange={(e) => setAuthName(e.target.value)}
                  placeholder={authType === "query" ? "api_key" : "X-API-Key"}
                />
              </Campo>
            )}
            <Campo
              label={authType === "oauth2_cc" ? "Client secret" : authType === "basic" ? "Usuario y contraseña" : "Clave"}
              hint={claveHint}
            >
              <input
                type="password"
                className={inputCls}
                value={authValue}
                onChange={(e) => setAuthValue(e.target.value)}
                placeholder={authType === "basic" ? "usuario:contraseña" : "••••••"}
              />
            </Campo>
          </div>
        )}

        <Campo label="Ruta al arreglo" hint="dónde está la lista en el JSON (ej. data); vacío si el cuerpo ya es la lista">
          <input className={inputCls} value={root} onChange={(e) => setRoot(e.target.value)} placeholder="data" />
        </Campo>

        <div>
          <p className="text-cuerpo font-semibold text-ink">Mapea los campos</p>
          <p className="mb-2 mt-0.5 text-apoyo text-ink-3">
            Qué campo del JSON es cada dato de aiuda. Usa puntos para anidar (ej. tel.movil).
          </p>
          <div className="space-y-2">
            {fields.map((f) => (
              <div key={f} className="flex items-center gap-2">
                <span className="w-24 shrink-0 text-cuerpo text-ink-2">{FIELD_LABEL[f] ?? f}</span>
                <input
                  className={inputCls}
                  value={mapping[f] ?? ""}
                  onChange={(e) => setMapping((m) => ({ ...m, [f]: e.target.value }))}
                  placeholder={f}
                />
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-line">
          <button
            type="button"
            onClick={() => setAvanzado(!avanzado)}
            className="flex w-full items-center justify-between px-3.5 py-2.5 text-left text-cuerpo font-medium text-ink transition-colors hover:bg-panel/40"
          >
            Avanzado: paginación, red y escritura
            <span className="text-apoyo font-normal text-ink-3">
              {avanzado ? "ocultar" : "mostrar"}
            </span>
          </button>
          {avanzado && (
            <div className="space-y-3 border-t border-line px-3.5 py-3">
              <Campo label="Paginación" hint="cómo pide aiuda la siguiente página">
                <select className={inputCls} value={paging} onChange={(e) => setPaging(e.target.value)}>
                  {PAGING_OPTIONS.map((o) => (
                    <option key={o.v} value={o.v}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </Campo>
              {paging === "offset" && (
                <div className="grid grid-cols-3 gap-3">
                  <Campo label="Param. corrimiento">
                    <input className={inputCls} value={pageParam} onChange={(e) => setPageParam(e.target.value)} placeholder="offset" />
                  </Campo>
                  <Campo label="Param. tamaño">
                    <input className={inputCls} value={sizeParam} onChange={(e) => setSizeParam(e.target.value)} placeholder="limit" />
                  </Campo>
                  <Campo label="Por página">
                    <input className={inputCls} inputMode="numeric" value={pageSize} onChange={(e) => setPageSize(e.target.value)} />
                  </Campo>
                </div>
              )}
              {paging === "cursor" && (
                <div className="grid grid-cols-2 gap-3">
                  <Campo label="Ruta al cursor" hint="en la respuesta (ej. meta.next)">
                    <input className={inputCls} value={cursorPath} onChange={(e) => setCursorPath(e.target.value)} placeholder="meta.next" />
                  </Campo>
                  <Campo label="Param. del cursor" hint="cómo se manda de regreso">
                    <input className={inputCls} value={cursorParam} onChange={(e) => setCursorParam(e.target.value)} placeholder="cursor" />
                  </Campo>
                </div>
              )}
              <div className="grid grid-cols-3 gap-3">
                <Campo label="Timeout (s)">
                  <input className={inputCls} inputMode="numeric" value={timeout_} onChange={(e) => setTimeout_(e.target.value)} />
                </Campo>
                <Campo label="Reintentos">
                  <input className={inputCls} inputMode="numeric" value={retries} onChange={(e) => setRetries(e.target.value)} />
                </Campo>
                <Campo label="Pausa entre páginas (ms)">
                  <input className={inputCls} inputMode="numeric" value={pauseMs} onChange={(e) => setPauseMs(e.target.value)} />
                </Campo>
              </div>
              <p className="text-apoyo leading-relaxed text-ink-3">
                aiuda acota todo con topes duros (máx. 60 s, 5 reintentos, 500 por página) y
                respeta el Retry-After de tu API si limita peticiones.
              </p>
              {/* Escritura: con write_path, esta conexión también RECIBE altas de aiuda
                  (aparece como destino en "Crear también en..." e "Inyectar a..."). */}
              <div className="grid grid-cols-2 gap-3 border-t border-line/60 pt-3">
                <Campo label="Ruta para dar de alta" hint="a dónde manda aiuda un registro nuevo; vacío = solo lee">
                  <input className={inputCls} value={writePath} onChange={(e) => setWritePath(e.target.value)} placeholder="clientes" />
                </Campo>
                <Campo label="Dónde viene el id creado" hint="el campo de la respuesta que lo trae (ej. data.id)">
                  <input className={inputCls} value={writeIdPath} onChange={(e) => setWriteIdPath(e.target.value)} placeholder="id" />
                </Campo>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={probar}
            disabled={!baseUrl.trim() || busy !== ""}
            className="rounded-md border border-line bg-surface px-3.5 py-2 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong disabled:opacity-50"
          >
            {busy === "test" ? "Probando…" : "Probar conexión"}
          </button>
          <PrimaryButton
            onClick={guardar}
            disabled={!baseUrl.trim() || !name.trim() || busy !== ""}
          >
            {busy === "save" ? "Guardando…" : editar ? "Guardar cambios" : "Guardar conexión"}
          </PrimaryButton>
        </div>

        {result &&
          (result.ok ? (
            <div className="rounded-lg bg-panel px-3.5 py-3 text-cuerpo">
              <p className="font-medium text-ok">
                Funciona · {result.count} registro{result.count === 1 ? "" : "s"} de muestra
              </p>
              {result.sample.length > 0 && (
                <pre className="mt-2 max-h-56 overflow-auto rounded bg-surface/80 p-2 text-apoyo leading-relaxed text-ink-2">
                  {JSON.stringify(result.sample, null, 2)}
                </pre>
              )}
            </div>
          ) : (
            <div className="rounded-lg bg-panel px-3.5 py-3 text-cuerpo text-danger">
              {result.error}
            </div>
          ))}
      </div>
    </Drawer>
  );
}
