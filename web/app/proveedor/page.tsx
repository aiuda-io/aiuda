"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  type ProviderName,
  type ProviderState,
  type ProviderTest,
  type SetupMaquina,
} from "@/lib/api";
import { PageHeader, Skeleton, ErrorState, useApi } from "@/components/ui";
import { SettingsField, SettingsPage, SettingsSection, settingsInputCls } from "@/components/settings";
import { toast } from "@/components/toast";

type SegOption<T extends string> = { value: T; label: string; badge?: string };

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
    <div role="radiogroup" aria-label={ariaLabel} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const activo = o.value === value;
        return (
          <button
            key={o.value}
            role="radio"
            aria-checked={activo}
            onClick={() => onChange(o.value)}
            className={`rounded-md border px-3 py-1.5 text-cuerpo font-medium transition-colors ${
              activo
                ? "border-accent bg-accent-soft text-accent-ink"
                : "border-line bg-surface text-ink-2 hover:border-line-strong hover:text-ink"
            }`}
          >
            {o.label}
            {o.badge && (
              <span className="ml-1.5 rounded bg-ok-soft px-1.5 py-px text-sello text-ok">
                {o.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export default function ProviderPage() {
  const { data: server, loading, error, refetch } = useApi<ProviderState>(api.provider);
  const [provider, setProvider] = useState<ProviderName>("claude");
  const [secret, setSecret] = useState("");
  const [localBaseUrl, setLocalBaseUrl] = useState("http://localhost:11434/v1");
  const [localModel, setLocalModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [tardando, setTardando] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ProviderTest | null>(null);
  const [maquina, setMaquina] = useState<SetupMaquina | null>(null);
  const escogio = useRef(false);

  useEffect(() => {
    api.setupMaquina().then(setMaquina).catch(() => setMaquina(null));
  }, []);

  const cliClaude = !!maquina?.clis.claude.instalado;
  const cliCodex = !!maquina?.clis.codex.instalado;
  const cliPorDefecto: ProviderName | null = cliClaude
    ? "claude_cli"
    : cliCodex
      ? "codex_cli"
      : null;

  useEffect(() => {
    if (!server) return;
    const p: ProviderName =
      !server.connected && !escogio.current && cliPorDefecto ? cliPorDefecto : server.name;
    setProvider(p);
    setSecret(server.connected && server.name === p ? server.secret : "");
    if (server.local_config) {
      setLocalBaseUrl(server.local_config.base_url);
      setLocalModel(server.local_config.model);
    }
  }, [server, cliPorDefecto]);

  function pickProvider(p: ProviderName) {
    escogio.current = true;
    setProvider(p);
    setTestResult(null);
    setSecret(server?.connected && server.name === p ? server.secret : "");
  }

  /** Prueba REAL: una llamada mínima por el mismo camino del motor. Nunca lanza. */
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

  async function guardar(name: ProviderName, valor: string) {
    setSaving(true);
    setTestResult(null);
    try {
      const modo = name === "claude_cli" || name === "codex_cli" ? "cli" : "api_key";
      await api.saveProvider(name, modo, valor);
      toast("Tu IA quedó conectada.", "success");
      refetch();
      probar();
    } catch (e) {
      toast(`No se pudo conectar: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  async function disconnect() {
    try {
      await api.disconnectProvider();
      toast("IA desconectada.", "info");
      refetch();
    } catch (e) {
      toast(`No se pudo desconectar: ${(e as Error).message}`, "error");
    }
  }

  if (error) return <ErrorState message={error} retry={refetch} />;

  const connectedHere = (server?.connected ?? false) && server?.name === provider;
  const esCli = provider === "claude_cli" || provider === "codex_cli";
  const marcaCli = provider === "claude_cli" ? "Claude Code" : "Codex";
  const statusPill = server ? (
    <span
      className={`rounded-full px-2.5 py-1 text-sello font-medium ${
        connectedHere ? "bg-ok-soft text-ok" : "bg-panel text-ink-2"
      }`}
    >
      {connectedHere
        ? "Conectada"
        : server.env_fallback && provider === "claude"
          ? "Activa por variable de entorno"
          : "Sin conectar"}
    </span>
  ) : null;

  return (
    <SettingsPage>
      <PageHeader
        title="Tu IA"
        subtitle="El motor que piensa por tus ayudantes. La pagas directo a quien la hace, o la corres gratis en esta computadora: aiuda no cobra por el uso ni revende nada."
        right={statusPill}
      />

      {/* Camino de actualización: si venías de la vía retirada, se dice qué pasó en vez
          de apagarte la IA en silencio. */}
      {server?.aviso_retirado && (
        <div className="mt-3 rounded-lg border border-warn/40 bg-warn-soft px-4 py-3">
          <p className="text-cuerpo font-semibold text-ink">Tu IA quedó desconectada</p>
          <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">{server.aviso_retirado}</p>
        </div>
      )}

      {loading && !server ? (
        <div className="mt-2 space-y-3">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
      ) : (
        <div className="mt-2">
          <SettingsSection
            title="De dónde sale tu IA"
            desc={
              cliPorDefecto
                ? `Ya tienes ${cliClaude ? "Claude Code" : "Codex"} en esta computadora: un clic y queda, sin pegar nada.`
                : "Tu llave, el programa que ya tengas instalado, o un modelo que corra aquí."
            }
          >
            <div className="space-y-4">
              <Segmented<ProviderName>
                ariaLabel="De dónde sale tu IA"
                value={provider}
                onChange={pickProvider}
                options={[
                  ...(cliClaude
                    ? [{ value: "claude_cli" as const, label: "Claude Code", badge: "ya instalado" }]
                    : []),
                  ...(cliCodex
                    ? [{ value: "codex_cli" as const, label: "Codex", badge: "ya instalado" }]
                    : []),
                  { value: "claude", label: "Claude con mi llave" },
                  { value: "codex", label: "OpenAI con mi llave" },
                  { value: "local", label: "En esta computadora" },
                ]}
              />

              {esCli ? (
                <div className="space-y-3">
                  <p className="text-cuerpo leading-relaxed text-ink-2">
                    Ya tienes {marcaCli} aquí y ya entraste con tu cuenta. Un clic y tus
                    ayudantes lo usan:{" "}
                    <strong className="font-semibold text-ink">
                      aiuda no guarda ninguna llave tuya
                    </strong>
                    , el programa se identifica solo con tu propia sesión.
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => guardar(provider, "")}
                      disabled={saving}
                      className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                    >
                      {saving ? "Conectando…" : connectedHere ? "Volver a conectar" : `Usar ${marcaCli}`}
                    </button>
                    {connectedHere && (
                      <>
                        <button
                          onClick={probar}
                          disabled={testing}
                          className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                        >
                          {testing ? "Probando…" : "Probar"}
                        </button>
                        <button
                          onClick={disconnect}
                          className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-danger hover:text-danger"
                        >
                          Desconectar
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ) : provider === "local" ? (
                <div className="space-y-3">
                  <p className="text-cuerpo leading-relaxed text-ink-2">
                    Un modelo corriendo en esta computadora (Ollama, LM Studio). Gratis y sin
                    internet:{" "}
                    <strong className="font-semibold text-ink">
                      ningún dato de tus clientes sale de aquí
                    </strong>
                    .
                  </p>
                  <SettingsField label="Dirección" hint="La que te da el programa que lo corre.">
                    <input
                      className={settingsInputCls}
                      value={localBaseUrl}
                      onChange={(e) => setLocalBaseUrl(e.target.value)}
                    />
                  </SettingsField>
                  <SettingsField label="Modelo" hint="El nombre tal como lo bajaste.">
                    <input
                      className={settingsInputCls}
                      placeholder="llama3.1"
                      value={localModel}
                      onChange={(e) => setLocalModel(e.target.value)}
                    />
                  </SettingsField>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={() =>
                        guardar(
                          "local",
                          JSON.stringify({
                            base_url: localBaseUrl.trim(),
                            model: localModel.trim(),
                          }),
                        )
                      }
                      disabled={saving || !localBaseUrl.trim()}
                      className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                    >
                      {saving ? "Conectando…" : "Conectar"}
                    </button>
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
                  <SettingsField
                    label={provider === "claude" ? "Llave de Anthropic" : "Llave de OpenAI"}
                    hint={
                      provider === "claude"
                        ? "La sacas en console.anthropic.com. Se guarda cifrada aquí y Anthropic te cobra a ti."
                        : "La sacas en platform.openai.com. Se guarda cifrada aquí y OpenAI te cobra a ti."
                    }
                  >
                    <input
                      className={settingsInputCls}
                      type="password"
                      placeholder={provider === "claude" ? "sk-ant-…" : "sk-…"}
                      value={secret}
                      onChange={(e) => setSecret(e.target.value)}
                    />
                  </SettingsField>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => guardar(provider, secret.trim())}
                      disabled={saving || !secret.trim()}
                      className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                    >
                      {saving ? "Conectando…" : connectedHere ? "Guardar" : "Conectar"}
                    </button>
                    {connectedHere && (
                      <>
                        <button
                          onClick={probar}
                          disabled={testing}
                          className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                        >
                          {testing ? "Probando…" : "Probar"}
                        </button>
                        <button
                          onClick={disconnect}
                          className="ml-auto rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-danger hover:text-danger"
                        >
                          Desconectar
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}

              {tardando && testing && (
                <p className="text-apoyo text-ink-3">
                  La primera vez tarda unos segundos: está despertando el programa.
                </p>
              )}
              {testResult && (
                <div
                  className={`rounded-lg border px-3.5 py-3 text-cuerpo leading-relaxed ${
                    testResult.ok
                      ? "border-ok/40 bg-ok-soft text-ok"
                      : "border-danger/40 bg-danger-soft text-danger"
                  }`}
                >
                  {testResult.ok
                    ? `Funciona. Respondió en ${testResult.latency_ms} ms.`
                    : testResult.error}
                </div>
              )}
            </div>
          </SettingsSection>

          <SettingsSection title="Qué se paga y a quién" desc="Para que no haya sorpresas.">
            <div className="space-y-2 text-cuerpo leading-relaxed text-ink-2">
              <p>
                <strong className="font-semibold text-ink">
                  aiuda no cobra por el uso de la IA ni la revende.
                </strong>{" "}
                Le pagas directo a quien la hace, o no le pagas a nadie si corres un modelo en
                esta computadora.
              </p>
              <p>
                Si usas el programa que ya tienes instalado, ocupa la cuenta con la que ya
                entraste ahí, igual que cuando lo abres tú. aiuda lo lanza y lee su respuesta:
                nunca ve ni guarda tu contraseña ni tu token.
              </p>
            </div>
          </SettingsSection>
        </div>
      )}
    </SettingsPage>
  );
}
