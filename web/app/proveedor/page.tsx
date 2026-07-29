"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  type ProviderMode,
  type ProviderName,
  type ProviderState,
  type ProviderTest,
  type SetupMaquina,
} from "@/lib/api";
import { PageHeader, Skeleton, ErrorState, useApi } from "@/components/ui";
import { SettingsField, SettingsPage, SettingsSection, settingsInputCls } from "@/components/settings";
import { toast } from "@/components/toast";

type SegOption<T extends string> = { value: T; label: string; badge?: string; disabled?: boolean };

function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: SegOption<T>[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="inline-flex flex-wrap rounded-md border border-line bg-panel p-0.5"
    >
      {options.map((o) => {
        const active = value === o.value;
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={active}
            disabled={o.disabled}
            title={o.disabled ? "Próximamente" : undefined}
            onClick={() => !o.disabled && onChange(o.value)}
            className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-cuerpo font-medium transition-colors ${
              active
                ? "bg-surface text-ink elev-sm"
                : o.disabled
                  ? "cursor-not-allowed text-ink-3/60"
                  : "text-ink-2 hover:text-ink"
            }`}
          >
            {o.label}
            {o.badge && (
              <span className="rounded bg-line/70 px-1 py-px text-rotulo font-semibold uppercase tracking-[0.04em] text-ink-3">
                {o.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// Nota honesta de la vía suscripción, sin alarmismo: aiuda corre en TU máquina
// con TU cuenta; solo se aclara que no es una vía oficial del proveedor.
function AvisoSuscripcion({
  proveedor,
  terminos,
  href,
}: {
  proveedor: string;
  terminos: string;
  href: string;
}) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-line bg-panel px-3.5 py-3">
      <svg viewBox="0 0 14 14" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-3" fill="none">
        <circle cx="7" cy="7" r="5.6" stroke="currentColor" strokeWidth="1.3" />
        <path d="M7 6.2v3.2M7 4.2h.01" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
      <div className="text-cuerpo leading-relaxed text-ink-2">
        <span className="font-semibold text-ink">Tu suscripción, en tu computadora.</span> aiuda
        corre local y usa tu propia cuenta de {proveedor}, como tus demás herramientas. Eso sí: no
        es una vía oficial según los{" "}
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-accent-ink underline-offset-2 hover:underline"
        >
          {terminos}
        </a>
        ; si prefieres cero letras chicas, usa tu API key o un modelo local (Ollama).
      </div>
    </div>
  );
}

export default function ProviderPage() {
  // Estado del servidor por el hook compartido (guarda de run-id + timeout honesto).
  const { data: server, error, loading, refetch } = useApi<ProviderState>(() => api.provider(), []);
  const [provider, setProvider] = useState<ProviderName>("claude");
  const [mode, setMode] = useState<ProviderMode>("api_key");
  const [secret, setSecret] = useState("");
  const [codexAuth, setCodexAuth] = useState("");
  // IA local (Ollama/OpenAI-compatible): base_url y modelo no son secretos.
  const [localBaseUrl, setLocalBaseUrl] = useState("http://localhost:11434/v1");
  const [localModel, setLocalModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [tardando, setTardando] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ProviderTest | null>(null);
  // La clave larga de `claude setup-token`: último recurso, vive detrás de una línea.
  const [claudeToken, setClaudeToken] = useState("");

  // Qué programas de IA ya están en esta computadora. Es un extra tolerante: si el
  // backend no lo trae, el panel funciona igual con las vías de siempre.
  const [maquina, setMaquina] = useState<SetupMaquina | null>(null);
  // El dueño ya escogió a mano: una radiografía que llegue tarde no le mueve nada.
  const escogio = useRef(false);

  useEffect(() => {
    api.setupMaquina().then(setMaquina, () => setMaquina(null));
  }, []);

  const cliClaude = !!maquina?.clis.claude.instalado;
  const cliCodex = !!maquina?.clis.codex.instalado;
  const cliPorDefecto: ProviderName | null = cliClaude
    ? "claude_cli"
    : cliCodex
      ? "codex_cli"
      : null;

  // Device code de OpenAI ("Iniciar sesión con ChatGPT"): el código de un solo uso vive aquí
  // mientras el dueño lo autoriza en su navegador; la consola sondea hasta conectar.
  const [device, setDevice] = useState<{
    userCode: string;
    url: string;
    deviceCode: string;
    interval: number;
    expiresAt: number;
  } | null>(null);
  const [devicePhase, setDevicePhase] = useState<"idle" | "starting" | "waiting" | "error">("idle");
  const [deviceError, setDeviceError] = useState("");
  const [now, setNow] = useState(() => Date.now());

  // ¿Este proveedor+modo tiene un campo de secreto (password) que sembrar enmascarado?
  // Claude y OpenAI solo en API key: la suscripción de OpenAI es device code y la de
  // Claude vive detrás de "otra forma", con su propio campo. El CLI de esta
  // computadora no tiene secreto: su sesión vive dentro del propio programa.
  function hasSecretField(name: ProviderName, m: ProviderMode) {
    return (name === "claude" || name === "codex") && m === "api_key";
  }

  function resetDevice() {
    setDevice(null);
    setDevicePhase("idle");
    setDeviceError("");
  }

  // El modo con el que se abre un proveedor que todavía no está conectado.
  function modoInicial(p: ProviderName): ProviderMode {
    if (p === "claude_cli" || p === "codex_cli") return "cli";
    if (p === "codex") return "subscription"; // entrar con tu cuenta, sin pegar nada
    return "api_key";
  }

  // La forma editable (proveedor/modo/secreto) se siembra del estado del servidor cada
  // vez que llega o recarga. Sin nada conectado manda el camino corto: si Claude Code o
  // Codex ya están en esta computadora, se abre en el de un clic.
  useEffect(() => {
    if (!server) return;
    const p: ProviderName =
      !server.connected && !escogio.current && cliPorDefecto ? cliPorDefecto : server.name;
    setProvider(p);
    const m: ProviderMode =
      (server.connected || server.name === "local") && p === server.name
        ? server.mode
        : modoInicial(p);
    setMode(m);
    setSecret(server.connected && p === server.name && hasSecretField(p, m) ? server.secret : "");
    if (server.local_config) {
      setLocalBaseUrl(server.local_config.base_url || "http://localhost:11434/v1");
      setLocalModel(server.local_config.model || "");
    }
    // cliPorDefecto llega tarde (la radiografía es otra petición): al llegar, re-siembra.
  }, [server, cliPorDefecto]);

  function pickProvider(p: ProviderName) {
    escogio.current = true;
    setProvider(p);
    setTestResult(null);
    resetDevice();
    const m: ProviderMode =
      server && server.connected && server.name === p ? server.mode : modoInicial(p);
    setMode(m);
    setSecret(server?.connected && server.name === p && hasSecretField(p, m) ? server.secret : "");
  }

  // Guarda la IA local: base_url + modelo viajan como JSON por el mismo camino cifrado.
  async function saveLocal() {
    setSaving(true);
    setTestResult(null);
    try {
      await api.saveProvider(
        "local",
        "api_key",
        JSON.stringify({ base_url: localBaseUrl.trim(), model: localModel.trim() }),
      );
      toast("IA local conectada.", "success");
      refetch();
      probar();
    } catch (e) {
      toast(`No se pudo conectar: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  // Al cambiar de modo, solo se rellena el secreto enmascarado si ese es el modo realmente
  // conectado; si no, se limpia (api key y token OAuth no son lo mismo). Cambiar de modo
  // también descarta cualquier device code en curso.
  function pickMode(m: ProviderMode) {
    setMode(m);
    resetDevice();
    setSecret(
      server && server.connected && server.name === provider && server.mode === m && hasSecretField(provider, m)
        ? server.secret
        : "",
    );
    setTestResult(null);
  }

  // Prueba REAL: una llamada mínima por el mismo camino del motor. Nunca lanza.
  async function probar() {
    setTesting(true);
    setTestResult(null);
    // Despertar un CLI la primera vez tarda (26 s medidos en frío, 3 s después):
    // si no se dice, "Probando…" se lee como colgado.
    setTardando(false);
    const avisoLento = window.setTimeout(() => setTardando(true), 6000);
    try {
      setTestResult(await api.testProvider());
    } catch (e) {
      setTestResult({ ok: false, code: "network", error: (e as Error).message });
    } finally {
      window.clearTimeout(avisoLento);
      setTardando(false);
      setTesting(false);
    }
  }

  // Guarda una credencial de secreto (API key de Claude/OpenAI o la clave de la cuenta de
  // Claude) por el mismo camino cifrado, y prueba la conexión de inmediato. La suscripción
  // de OpenAI NO pasa por aquí (es device code).
  async function savePassword(name: ProviderName, m: ProviderMode, value: string) {
    setSaving(true);
    setTestResult(null);
    try {
      await api.saveProvider(name, m, value);
      toast("Proveedor conectado.", "success");
      refetch();
      probar();
    } catch (e) {
      toast(`No se pudo conectar: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  // Un clic: el programa ya está aquí con la sesión del dueño. No se guarda ningún
  // secreto suyo, solo queda anotado qué usar. La prueba tarda unos segundos porque
  // corre el programa de verdad.
  async function usarCli(name: "claude_cli" | "codex_cli") {
    setSaving(true);
    setTestResult(null);
    try {
      await api.saveProvider(name, "cli", "");
      toast(`${name === "claude_cli" ? "Claude Code" : "Codex"} conectado.`, "success");
      refetch();
      probar();
    } catch (e) {
      toast(`No se pudo conectar: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  // Arranca el device code: pide el código a OpenAI y entra en modo "esperando". El efecto de
  // sondeo se encarga del resto.
  async function startDevice() {
    setDevicePhase("starting");
    setDeviceError("");
    setTestResult(null);
    try {
      const res = await api.startOpenaiDevice();
      setDevice({
        userCode: res.user_code,
        url: res.verification_uri,
        deviceCode: res.device_code,
        interval: Math.max(1, res.interval || 5),
        expiresAt: Date.now() + (res.expires_in || 900) * 1000,
      });
      setNow(Date.now());
      setDevicePhase("waiting");
    } catch (e) {
      setDevicePhase("error");
      setDeviceError((e as Error).message);
    }
  }

  async function copyCode() {
    if (!device) return;
    try {
      await navigator.clipboard.writeText(device.userCode);
      toast("Código copiado.", "success");
    } catch {
      toast("No se pudo copiar. Cópialo a mano.", "error");
    }
  }

  // La línea que el dueño pega en la app Terminal para generar la clave de su cuenta.
  async function copyComando() {
    try {
      await navigator.clipboard.writeText("claude setup-token");
      toast("Línea copiada.", "success");
    } catch {
      toast("No se pudo copiar. Escríbela tal cual.", "error");
    }
  }

  // Sondeo del device code: cada `interval` segundos pregunta si el dueño ya autorizó. Al
  // conectar muestra el veredicto verde; al vencer o fallar, un aviso honesto. Se limpia solo
  // al cambiar de modo/proveedor o al desmontar.
  useEffect(() => {
    if (!device || devicePhase !== "waiting") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (cancelled) return;
      if (Date.now() >= device.expiresAt) {
        setDevicePhase("error");
        setDeviceError("El código venció. Genera uno nuevo.");
        return;
      }
      try {
        const res = await api.pollOpenaiDevice(device.deviceCode, device.userCode);
        if (cancelled) return;
        if (res.status === "success") {
          resetDevice();
          setTestResult(res.test ?? null);
          toast("OpenAI conectado.", "success");
          refetch();
          return;
        }
        if (res.status === "error") {
          setDevicePhase("error");
          setDeviceError(res.detail || "No se pudo autorizar con OpenAI.");
          return;
        }
        timer = setTimeout(poll, device.interval * 1000); // pendiente: sigue sondeando
      } catch {
        // Hipo de red: reintenta hasta la expiración, no tumbes el flujo.
        if (!cancelled) timer = setTimeout(poll, device.interval * 1000);
      }
    };
    timer = setTimeout(poll, device.interval * 1000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // refetch/toast son estables en la práctica; no se listan para no reiniciar el sondeo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device, devicePhase]);

  // Cuenta regresiva del código (solo tic de reloj para el mm:ss).
  useEffect(() => {
    if (!device || devicePhase !== "waiting") return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [device, devicePhase]);

  async function connectOpenai() {
    setConnecting(true);
    setTestResult(null);
    try {
      const res = await api.connectOpenai(codexAuth.trim() || undefined);
      toast("OpenAI conectado.", "success");
      setTestResult(res.test ?? null);
      setCodexAuth("");
      refetch();
    } catch (e) {
      toast(`No se pudo conectar: ${(e as Error).message}`, "error");
    } finally {
      setConnecting(false);
    }
  }

  async function disconnect() {
    try {
      await api.disconnectProvider();
      toast("Proveedor desconectado.", "info");
      refetch();
    } catch (e) {
      toast(`No se pudo desconectar: ${(e as Error).message}`, "error");
    }
  }

  if (error) return <ErrorState message={error} retry={refetch} />;

  const connectedHere = (server?.connected ?? false) && server?.name === provider;
  const conectadoConLlave = connectedHere && server?.mode === "api_key";
  const esCli = provider === "claude_cli" || provider === "codex_cli";
  const marcaCli = provider === "claude_cli" ? "Claude Code" : "Codex";
  // Cuenta regresiva del código de dispositivo (mm:ss) mientras el dueño lo autoriza.
  const deviceSecsLeft = device ? Math.max(0, Math.ceil((device.expiresAt - now) / 1000)) : 0;
  const deviceCountdown = `${Math.floor(deviceSecsLeft / 60)}:${String(deviceSecsLeft % 60).padStart(2, "0")}`;
  const statusPill = server ? (
    <span
      className={`rounded-full px-2.5 py-1 text-sello font-medium ${
        connectedHere ? "bg-ok-soft text-ok" : "bg-panel text-ink-2"
      }`}
    >
      {connectedHere
        ? "Conectado"
        : server.env_fallback && provider === "claude"
          ? "Activo por variable de entorno"
          : "Sin conectar"}
    </span>
  ) : null;

  return (
    <SettingsPage>
      <PageHeader
        title="Proveedor de IA"
        subtitle="El motor que piensa por tus ayudantes: Claude, OpenAI (ChatGPT) o un modelo local en tu propia máquina."
        right={statusPill}
      />

      {loading && !server ? (
        <div className="mt-2 space-y-3">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
      ) : (
        <div className="mt-2">
          <SettingsSection
            title="Cómo conectar"
            desc={
              cliPorDefecto
                ? `Ya tienes ${cliClaude ? "Claude Code" : "Codex"} en esta computadora: un clic y queda. Si prefieres otra cosa, también puedes pegar tu llave o usar un modelo que corra aquí.`
                : "Elige de dónde sale tu IA: entrando con la cuenta que ya pagas, pegando tu llave, o con un modelo que corre en esta computadora."
            }
          >
            <div className="space-y-4">
              <Segmented<ProviderName>
                ariaLabel="Proveedor de IA"
                value={provider}
                onChange={pickProvider}
                options={[
                  // Lo que YA está en esta computadora va primero: es el camino de un clic.
                  ...(cliClaude
                    ? [{ value: "claude_cli" as const, label: "Claude Code" }]
                    : []),
                  ...(cliCodex ? [{ value: "codex_cli" as const, label: "Codex" }] : []),
                  { value: "claude", label: "Claude" },
                  { value: "codex", label: "OpenAI (ChatGPT)" },
                  { value: "local", label: "IA local (Ollama)" },
                ]}
              />

              {esCli ? (
                /* Un clic: el programa ya está aquí, con la sesión del dueño. */
                <div className="space-y-3">
                  <p className="text-cuerpo leading-relaxed text-ink-2">
                    Ya tienes {marcaCli} en esta computadora y ya entraste ahí con tu cuenta. Un
                    clic y tus ayudantes lo usan: aiuda no guarda ninguna llave tuya.
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => usarCli(provider === "claude_cli" ? "claude_cli" : "codex_cli")}
                      disabled={saving}
                      className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                    >
                      {saving
                        ? "Conectando…"
                        : connectedHere
                          ? "Volver a conectar"
                          : `Usar ${marcaCli}`}
                    </button>
                    {connectedHere && (
                      <button
                        onClick={probar}
                        disabled={testing}
                        className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                      >
                        {testing ? "Probando…" : "Probar conexión"}
                      </button>
                    )}
                    {connectedHere && (
                      <button
                        onClick={disconnect}
                        className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-danger hover:text-danger"
                      >
                        Desconectar
                      </button>
                    )}
                  </div>
                  <AvisoSuscripcion
                    proveedor={provider === "claude_cli" ? "Claude" : "OpenAI (ChatGPT)"}
                    terminos={
                      provider === "claude_cli"
                        ? "términos de Anthropic"
                        : "usos documentados por OpenAI"
                    }
                    href={
                      provider === "claude_cli"
                        ? "https://www.anthropic.com/legal/consumer-terms"
                        : "https://developers.openai.com/codex/auth"
                    }
                  />
                </div>
              ) : provider === "claude" ? (
                <>
                  <SettingsField
                    label="API key de Anthropic"
                    hint={
                      <>
                        La vía recomendada y soportada. Crea una key en{" "}
                        <a
                          href="https://console.anthropic.com"
                          target="_blank"
                          rel="noreferrer"
                          className="font-medium text-accent-ink underline-offset-2 hover:underline"
                        >
                          console.anthropic.com
                        </a>
                        . Se guarda cifrada, solo para tu negocio.
                      </>
                    }
                  >
                    <input
                      id="secret"
                      className={settingsInputCls}
                      type="password"
                      placeholder="sk-ant-…"
                      value={secret}
                      onChange={(e) => setSecret(e.target.value)}
                    />
                  </SettingsField>

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => savePassword("claude", "api_key", secret)}
                      disabled={saving || !secret.trim()}
                      className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                    >
                      {saving ? "Conectando…" : conectadoConLlave ? "Guardar cambios" : "Conectar"}
                    </button>
                    {connectedHere && (
                      <button
                        onClick={probar}
                        disabled={testing}
                        className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                      >
                        {testing ? "Probando…" : "Probar conexión"}
                      </button>
                    )}
                    {connectedHere && (
                      <button
                        onClick={disconnect}
                        className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-danger hover:text-danger"
                      >
                        Desconectar
                      </button>
                    )}
                  </div>

                  {/* Último recurso. La vía de un clic es Claude Code; esto queda por si
                      alguien insiste en la clave de su cuenta, y solo aquí, nunca en el
                      asistente de primer arranque. */}
                  <details className="rounded-lg border border-line bg-panel/40 px-3.5 py-2.5">
                    <summary className="cursor-pointer text-cuerpo font-medium text-ink-2 hover:text-ink">
                      Usar la clave de mi cuenta (avanzado)
                    </summary>
                    <div className="mt-3 space-y-3">
                      <p className="text-cuerpo leading-relaxed text-ink-2">
                        En la app Terminal corre{" "}
                        <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-sello text-ink">
                          claude setup-token
                        </code>{" "}
                        <button
                          onClick={copyComando}
                          className="font-medium text-accent-ink hover:underline"
                        >
                          (copiar)
                        </button>{" "}
                        y pega aquí la clave larga que te devuelve. Se guarda cifrada, solo para tu
                        negocio.
                      </p>
                      <SettingsField label="Clave de tu cuenta de Claude">
                        <input
                          className={settingsInputCls}
                          type="password"
                          placeholder="Pega la clave larga"
                          value={claudeToken}
                          onChange={(e) => setClaudeToken(e.target.value)}
                        />
                      </SettingsField>
                      <button
                        onClick={() => savePassword("claude", "subscription", claudeToken.trim())}
                        disabled={saving || !claudeToken.trim()}
                        className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                      >
                        {saving ? "Conectando…" : "Conectar con la clave de mi cuenta"}
                      </button>
                      <AvisoSuscripcion
                        proveedor="Claude"
                        terminos="términos de Anthropic"
                        href="https://www.anthropic.com/legal/consumer-terms"
                      />
                    </div>
                  </details>
                </>
              ) : provider === "local" ? (
                <div className="space-y-3">
                  <SettingsField
                    label="Endpoint OpenAI-compatible"
                    hint="Ollama, LM Studio o vLLM corriendo en tu máquina. Con Ollama, el default de abajo ya sirve."
                  >
                    <input
                      className={settingsInputCls}
                      placeholder="http://localhost:11434/v1"
                      value={localBaseUrl}
                      onChange={(e) => setLocalBaseUrl(e.target.value)}
                    />
                  </SettingsField>
                  <SettingsField
                    label="Modelo"
                    hint={
                      <>
                        El nombre exacto que lista{" "}
                        <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-sello text-ink">
                          ollama list
                        </code>{" "}
                        (p.ej. llama3.1, qwen2.5). Necesita soportar tool calling para los ayudantes.
                      </>
                    }
                  >
                    <input
                      className={settingsInputCls}
                      placeholder="llama3.1"
                      value={localModel}
                      onChange={(e) => setLocalModel(e.target.value)}
                    />
                  </SettingsField>
                  <p className="text-apoyo leading-relaxed text-ink-3">
                    La única vía donde ningún dato sale de tu computadora. A cambio, la
                    calidad depende del modelo que corras: prueba y decide.
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={saveLocal}
                      disabled={saving || !localModel.trim()}
                      className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                    >
                      {saving ? "Conectando…" : connectedHere ? "Guardar cambios" : "Conectar"}
                    </button>
                    {connectedHere && (
                      <button
                        onClick={probar}
                        disabled={testing}
                        className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                      >
                        {testing ? "Probando…" : "Probar conexión"}
                      </button>
                    )}
                    {connectedHere && (
                      <button
                        onClick={disconnect}
                        className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-danger hover:text-danger"
                      >
                        Desconectar
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="text-cuerpo text-ink-3">Cómo entrar</span>
                    <Segmented<ProviderMode>
                      ariaLabel="Cómo conectar OpenAI"
                      value={mode}
                      onChange={pickMode}
                      options={[
                        { value: "subscription", label: "Mi cuenta" },
                        { value: "api_key", label: "Mi llave (API key)" },
                      ]}
                    />
                  </div>

                  {mode === "api_key" ? (
                    <div className="space-y-3">
                      <SettingsField
                        label="API key de OpenAI"
                        hint={
                          <>
                            La vía recomendada y soportada. Crea una key en{" "}
                            <a
                              href="https://platform.openai.com/api-keys"
                              target="_blank"
                              rel="noreferrer"
                              className="font-medium text-accent-ink underline-offset-2 hover:underline"
                            >
                              platform.openai.com
                            </a>
                            . Se guarda cifrada, solo para tu negocio.
                          </>
                        }
                      >
                        <input
                          id="secret"
                          className={settingsInputCls}
                          type="password"
                          placeholder="sk-…"
                          value={secret}
                          onChange={(e) => setSecret(e.target.value)}
                        />
                      </SettingsField>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          onClick={() => savePassword("codex", "api_key", secret)}
                          disabled={saving || !secret.trim()}
                          className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                        >
                          {saving ? "Conectando…" : conectadoConLlave ? "Guardar cambios" : "Conectar"}
                        </button>
                        {connectedHere && (
                          <button
                            onClick={probar}
                            disabled={testing}
                            className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                          >
                            {testing ? "Probando…" : "Probar conexión"}
                          </button>
                        )}
                        {connectedHere && (
                          <button
                            onClick={disconnect}
                            className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-danger hover:text-danger"
                          >
                            Desconectar
                          </button>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <p className="text-cuerpo leading-relaxed text-ink-2">
                        Entra con la misma cuenta con la que usas ChatGPT, sin salir de aquí: aiuda
                        te da un código de un solo uso y lo escribes en la página de OpenAI. Una
                        sola vez, activa{" "}
                        <a
                          href="https://developers.openai.com/codex/auth"
                          target="_blank"
                          rel="noreferrer"
                          className="font-medium text-accent-ink underline-offset-2 hover:underline"
                        >
                          el inicio de sesión con código
                        </a>{" "}
                        en ChatGPT, Configuración, Seguridad (viene apagado).
                      </p>

                      {devicePhase === "waiting" && device ? (
                        <div className="space-y-3 rounded-lg border border-line bg-panel/50 px-3.5 py-3.5">
                          <p className="text-cuerpo leading-relaxed text-ink-2">
                            Escribe este código en la página de OpenAI:
                          </p>
                          <div className="flex items-center gap-2">
                            <code className="tnum flex-1 rounded-md border border-line bg-surface px-3 py-2 text-center text-seccion font-semibold tracking-[0.18em] text-ink">
                              {device.userCode}
                            </code>
                            <button
                              onClick={copyCode}
                              className="rounded-md border border-line bg-surface px-3 py-2 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
                            >
                              Copiar
                            </button>
                          </div>
                          <a
                            href={device.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong"
                          >
                            Abrir la página de OpenAI
                          </a>
                          <div className="flex items-start gap-2 text-cuerpo text-ink-3">
                            <span className="breathe mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent" />
                            <span>
                              Esperando a que autorices… El código vence en{" "}
                              <span className="tnum font-medium text-ink-2">{deviceCountdown}</span>.
                            </span>
                          </div>
                        </div>
                      ) : (
                        <button
                          onClick={startDevice}
                          disabled={devicePhase === "starting"}
                          className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                        >
                          {devicePhase === "starting"
                            ? "Preparando…"
                            : connectedHere
                              ? "Reconectar con ChatGPT"
                              : "Iniciar sesión con ChatGPT"}
                        </button>
                      )}

                      {devicePhase === "error" && (
                        <div className="flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-2.5">
                          <svg viewBox="0 0 12 12" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" fill="none" aria-hidden="true">
                            <path d="M3.5 3.5 8.5 8.5M8.5 3.5 3.5 8.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                          <p className="text-cuerpo leading-relaxed text-ink-2">{deviceError}</p>
                        </div>
                      )}

                      <AvisoSuscripcion
                        proveedor="OpenAI (ChatGPT)"
                        terminos="usos documentados por OpenAI"
                        href="https://developers.openai.com/codex/auth"
                      />

                      {(connectedHere || devicePhase === "waiting") && (
                        <div className="flex flex-wrap items-center gap-2">
                          {connectedHere && (
                            <button
                              onClick={probar}
                              disabled={testing}
                              className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                            >
                              {testing ? "Probando…" : "Probar conexión"}
                            </button>
                          )}
                          {devicePhase === "waiting" && (
                            <button
                              onClick={resetDevice}
                              className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-line-strong hover:text-ink"
                            >
                              Cancelar
                            </button>
                          )}
                          {connectedHere && (
                            <button
                              onClick={disconnect}
                              className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-danger hover:text-danger"
                            >
                              Desconectar
                            </button>
                          )}
                        </div>
                      )}

                      {/* Fallback de power-user / self-host: pegar el auth.json a mano. */}
                      <details className="rounded-lg border border-line bg-panel/40 px-3.5 py-2.5">
                        <summary className="cursor-pointer text-cuerpo font-medium text-ink-2 hover:text-ink">
                          Pegar la sesión a mano (avanzado)
                        </summary>
                        <div className="mt-3 space-y-3">
                          <SettingsField
                            label="Sesión de ChatGPT (auth.json)"
                            hint={
                              <>
                                Si prefieres, en tu máquina corre{" "}
                                <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-sello text-ink">
                                  codex login
                                </code>{" "}
                                y pega aquí el contenido de{" "}
                                <code className="rounded bg-panel px-1.5 py-0.5 font-mono text-sello text-ink">
                                  ~/.codex/auth.json
                                </code>
                                . Se guarda cifrado, solo para tu negocio.
                              </>
                            }
                          >
                            <textarea
                              className={`${settingsInputCls} h-24 resize-y font-mono text-apoyo`}
                              placeholder={'{ "tokens": { "access_token": "…", "refresh_token": "…", "account_id": "…" } }'}
                              value={codexAuth}
                              onChange={(e) => setCodexAuth(e.target.value)}
                            />
                          </SettingsField>
                          <button
                            onClick={connectOpenai}
                            disabled={connecting || !codexAuth.trim()}
                            className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                          >
                            {connecting ? "Conectando…" : "Conectar con el auth.json"}
                          </button>
                        </div>
                      </details>
                    </div>
                  )}
                </>
              )}

              {/* Veredicto de la prueba REAL: verde con latencia, o el error honesto. */}
              {(testing || connecting || testResult) && (
                <div>
                  {testing || connecting ? (
                    <div className="flex items-center gap-2.5 rounded-lg border border-line bg-panel/50 px-3.5 py-2.5 text-cuerpo text-ink-2">
                      <span className="breathe h-2 w-2 rounded-full bg-accent" />
                      {connecting ? "Conectando con OpenAI…" : "Probando la conexión…"}
                      {tardando && !connecting && (
                        <span className="text-ink-3">
                          La primera vez tarda un poco: tu programa está despertando.
                        </span>
                      )}
                    </div>
                  ) : testResult?.ok ? (
                    <div className="flex items-start gap-2.5 rounded-lg border border-ok/30 bg-ok-soft px-3.5 py-2.5">
                      <svg viewBox="0 0 12 12" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" fill="none" aria-hidden="true">
                        <path d="m2.5 6.5 2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <p className="text-cuerpo leading-relaxed text-ink-2">
                        <span className="font-semibold text-ok">Verificado.</span> Respondió en{" "}
                        <span className="tnum font-medium text-ink">{testResult.latency_ms} ms</span> por{" "}
                        {testResult.mode === "cli"
                          ? "el programa de esta computadora"
                          : testResult.mode === "subscription"
                            ? "tu suscripción"
                            : "tu API key"}{" "}
                        ({testResult.model}).
                      </p>
                    </div>
                  ) : testResult ? (
                    <div className="flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-2.5">
                      <svg viewBox="0 0 12 12" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" fill="none" aria-hidden="true">
                        <path d="M3.5 3.5 8.5 8.5M8.5 3.5 3.5 8.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <p className="text-cuerpo leading-relaxed text-ink-2">
                        <span className="font-semibold text-danger">No respondió.</span> {testResult.error}
                      </p>
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          </SettingsSection>

          {server?.env_fallback && !connectedHere && provider === "claude" && (
            <p className="px-1 text-apoyo leading-relaxed text-ink-3">
              Hay una API key configurada por variable de entorno, así que tus ayudantes ya
              responden. Conectar aquí la reemplaza para este negocio.
            </p>
          )}
        </div>
      )}
    </SettingsPage>
  );
}
