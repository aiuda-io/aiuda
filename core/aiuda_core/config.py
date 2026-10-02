from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def propia(nombre: str) -> AliasChoices:
    """Acepta `SCHEDULER_ENABLED` y `AIUDA_SCHEDULER_ENABLED`.

    Los nombres cortos son cómodos, pero `WORKSPACE_ID` o `SESSION_TOKEN` son
    tan genéricos que otra herramienta del sistema podría tenerlos puestos y
    aiuda obedecería sin que nadie lo pidiera. Se aceptan ambos y se documenta
    el prefijado, que es el que no choca con nada."""
    return AliasChoices(nombre.upper(), f"AIUDA_{nombre.upper()}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Vacío = SQLite local en ~/.aiuda/aiuda.db (el default de la instalación en
    # tu computadora; lo resuelve aiuda_core.db). Ponlo solo para usar Postgres
    # (p.ej. una instancia operada para varios usuarios):
    # postgresql+psycopg://usuario:clave@host:5432/aiuda (requiere el extra
    # `aiuda-server[postgres]`).
    database_url: str = Field("", validation_alias=propia("database_url"))

    # Corrida horaria automática (hilo del scheduler dentro del proceso del API).
    # Apagable para tests o para correr el API sin trabajos de fondo.
    scheduler_enabled: bool = Field(True, validation_alias=propia("scheduler_enabled"))

    # Token de sesión local (patrón Jupyter): `aiuda start` genera uno por
    # arranque y abre el navegador con ?token=...; el API lo canjea por cookie.
    # Vacío = sin guardia (dev/tests). El bind sigue siendo 127.0.0.1.
    session_token: str = Field("", validation_alias=propia("session_token"))

    # Workspace activo cuando una base importada trae varios. Vacío = el más
    # antiguo. En una instalación nueva nunca hace falta.
    workspace_id: str = Field("", validation_alias=propia("workspace_id"))

    anthropic_api_key: str = Field("", validation_alias=propia("anthropic_api_key"))
    # Modelos por tarea: Haiku clasifica/triage, Sonnet redacta y razona cartera.
    model_triage: str = "claude-haiku-4-5"
    model_redaccion: str = "claude-sonnet-4-6"
    # OpenAI por la Responses API estándar. Un mismo modelo cubre triage y redacción
    # (no hay un equivalente barato de haiku).
    model_codex: str = "gpt-5.5"
    model_codex_triage: str = "gpt-5.5"

    # Canal de WhatsApp: "wacli" (CLI de terceros) o "evolution" (Evolution API)
    whatsapp_provider: str = "wacli"
    # Comando de envío de wacli; placeholders {bin}, {phone} y {message}.
    # wacli 0.8.x: `send` exige el subcomando `text` con --to/--message; --lock-wait
    # hace que el envío espere el lock si hay un `wacli sync` corriendo en vez de fallar.
    wacli_send_template: str = "{bin} send text --to {phone} --message {message} --lock-wait 30s"
    # Binario de wacli (lo usan el emparejado por QR y, vía {bin}, el envío).
    wacli_bin: str = "wacli"
    # El cuello de botella del envío: `wacli sync --follow` retiene el lock del store y
    # `wacli send` espera ~30s a que se libere. Solución (igual que fastapi_service): pausar
    # el sync justo antes de enviar y reiniciarlo al terminar. Comandos de shell; si ambos
    # quedan vacíos, no se toca el sync (el envío cae al --lock-wait de la plantilla).
    #   macOS local:  launchctl unload/load ~/Library/LaunchAgents/sh.wacli.sync.plist
    #   server Linux: systemctl stop/start wacli-sync.service
    wacli_sync_stop_cmd: str = ""
    wacli_sync_start_cmd: str = ""
    # Segundos de espera tras pausar el sync para que suelte el lock antes de enviar.
    wacli_sync_settle_secs: float = 0.4
    # Raíz de stores de wacli por workspace: cada instancia usa <root>/<instance>
    # vía la flag global --store (sesión y datos aislados; cada negocio su número).
    # Vacío = store default del host.
    wacli_store_root: str = ""

    # WhatsApp Business Cloud API (Meta) — la vía OFICIAL del canal. Credenciales de
    # envío por tenant (cifradas); esto es solo lo de la app/webhook a nivel servidor.
    waba_base_url: str = "https://graph.facebook.com/v23.0"
    # Verify token del webhook (lo eliges tú y lo capturas igual en el panel de Meta).
    waba_verify_token: str = ""
    # App secret de la app de Meta: valida la firma X-Hub-Signature-256 del webhook.
    # Sin él, el webhook oficial rechaza los POST (no se aceptan eventos sin firma).
    waba_app_secret: str = ""

    # Llamadas de voz (Twilio) — canal de recordatorios por teléfono. Las credenciales
    # de la cuenta van por tenant (cifradas, provider twilio_voz); esto es solo la URL
    # PÚBLICA a la que Twilio avisa el resultado de cada llamada (StatusCallback). Vacío
    # = no se pide callback (la llamada igual se hace, solo no llega el veredicto).
    twilio_voz_status_callback_url: str = ""

    # Evolution API (WhatsApp)
    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_webhook_token: str = ""

    # Belvo · open banking MX (detección de pagos). Sandbox por default.
    belvo_base_url: str = "https://sandbox.belvo.com"
    belvo_secret_id: str = ""
    belvo_secret_password: str = ""

    # Facturama · PAC para CFDI (SAT). Sandbox por default.
    facturama_base_url: str = "https://apisandbox.facturama.mx"
    facturama_user: str = ""
    facturama_password: str = ""

    # DENUE · INEGI (directorio público de 5.5M unidades económicas)
    denue_token: str = ""

    # Google Calendar (token OAuth/service account ya emitido)
    google_calendar_token: str = ""
    google_calendar_id: str = "primary"

    # Facturapi · PAC alternativo developer-friendly (key sk_test_… en sandbox)
    facturapi_api_key: str = ""

    # Shopify · Custom App de la tienda del usuario (sin review)
    shopify_store_domain: str = ""  # ej. mitienda.myshopify.com
    shopify_access_token: str = ""

    # WooCommerce · REST API del wp-admin del usuario
    woocommerce_base_url: str = ""  # ej. https://mitienda.mx
    woocommerce_consumer_key: str = ""
    woocommerce_consumer_secret: str = ""

    # Stripe · pagos (detección de cobros del negocio).
    stripe_api_key: str = ""

    # Pasarelas de cobro para el ayudante (link de pago por WhatsApp + confirmación).
    # Las credenciales van por tenant (cifradas); esto es fallback self-host.
    mercadopago_access_token: str = ""  # APP_USR-… (Mercado Pago)
    clip_api_key: str = ""  # API key del portal de Clip
    conekta_api_key: str = ""  # private key (OXXO Pay / SPEI / tarjeta)

    # Google Sheets · una hoja compartida ("cualquiera con el link · lector") leída
    # por API key con la Sheets API v4. spreadsheet_id/range/tipo son operativos: el
    # dueño los captura en la UI (viven en la credencial), aquí sirven al self-host.
    google_sheets_api_key: str = ""
    google_sheets_spreadsheet_id: str = ""
    google_sheets_range: str = ""  # ej. Facturas!A:F
    google_sheets_tipo: str = ""  # facturas | clientes | productos

    # Mercado Libre · app oficial del vendedor (OAuth). El access_token dura 6 h; con
    # client_id/client_secret/refresh_token aiuda lo refresca al 401 (el refresh_token
    # de ML es de un solo uso: la corrida guarda el par nuevo cifrado).
    mercadolibre_access_token: str = ""
    mercadolibre_refresh_token: str = ""
    mercadolibre_client_id: str = ""
    mercadolibre_client_secret: str = ""
    mercadolibre_seller_id: str = ""  # opcional: si falta, se resuelve con /users/me

    # Slack · bot token instalado por el admin del workspace + canal de avisos
    slack_bot_token: str = ""
    slack_channel: str = ""  # ej. #cobranza — a dónde salen los avisos internos

    # HubSpot · private app token de la cuenta del usuario
    hubspot_token: str = ""

    # Clave(s) Fernet para cifrar credenciales por tenant. Formato: "2:<keyB>,1:<keyA>"
    # (rotación) o una sola. En prod/VPS llega como variable de entorno real; aquí se
    # declara para que un .env local también funcione (cripto lee env var O este valor).
    aiuda_encryption_keys: str = ""

    # Orígenes permitidos para CORS, coma-separados. La consola habla same-origin
    # (rewrite /api), así que esto es para clientes externos o dev directo.
    cors_origins: str = "http://localhost:3000"

    # Observabilidad: DSN de Sentry para capturar errores en prod. Vacío = solo
    # stdout. Activarlo: instalar sentry-sdk + definir el DSN.
    sentry_dsn: str = ""

    environment: str = "dev"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

settings = Settings()
