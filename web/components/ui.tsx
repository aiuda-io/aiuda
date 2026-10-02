"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { BUCKET_META } from "@/lib/api";

export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-titulo font-semibold text-ink">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-2xl text-cuerpo text-ink-2">{subtitle}</p>}
      </div>
      {right}
    </header>
  );
}

export function BucketPill({ bucket }: { bucket: string }) {
  const meta = BUCKET_META[bucket] ?? {
    label: bucket,
    fg: "text-ink-2",
    bg: "bg-line/50",
  };
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-sello font-medium ${meta.bg} ${meta.fg}`}
    >
      {meta.label}
    </span>
  );
}

export function ChevronLeft({ className = "h-3 w-3" }: { className?: string }) {
  return (
    <svg viewBox="0 0 12 12" className={className} fill="none" aria-hidden="true">
      <path d="m7 3-3 3 3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Tamaños compartidos por los primitivos de botón/liga: una sola escala (no
 *  padding/tipografía a mano). `md` es el default e IDÉNTICO al estilo previo;
 *  `sm` es para acciones inline compactas (ej. "Editar" junto a un título). */
const BTN_SIZE = {
  sm: "px-2.5 py-1 text-rotulo",
  md: "px-3.5 py-2 text-cuerpo",
  /** Superficies de pantalla completa (asistente de primer arranque): el botón
   *  es el objeto principal de la vista y la densidad de consola queda chica. */
  lg: "px-5 py-3 text-seccion",
} as const;
type BtnSize = keyof typeof BTN_SIZE;

export function PrimaryButton({
  size = "md",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { size?: BtnSize }) {
  return (
    <button
      {...props}
      className={`rounded-md bg-accent font-medium text-surface transition-colors hover:bg-accent-strong active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50 ${BTN_SIZE[size]} ${className ?? ""}`}
    />
  );
}

export function SecondaryButton({
  size = "md",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { size?: BtnSize }) {
  return (
    <button
      {...props}
      className={`rounded-md border border-line bg-surface font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50 ${BTN_SIZE[size]} ${className ?? ""}`}
    />
  );
}

/** Ligas con ropa de botón: para CTAs que navegan (el "primer valor" de los
 *  estados vacíos deep-linkea a donde se resuelve). Mismas clases que los botones.
 *  `external` abre en pestaña nueva con rel seguro (ligas a fuentes externas). */
export function PrimaryLink({
  href,
  size = "md",
  external,
  children,
}: {
  href: string;
  size?: BtnSize;
  external?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noreferrer" : undefined}
      className={`inline-flex rounded-md bg-accent font-medium text-surface transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${BTN_SIZE[size]}`}
    >
      {children}
    </Link>
  );
}

export function SecondaryLink({
  href,
  size = "md",
  external,
  children,
}: {
  href: string;
  size?: BtnSize;
  external?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noreferrer" : undefined}
      className={`inline-flex rounded-md border border-line bg-surface font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${BTN_SIZE[size]}`}
    >
      {children}
    </Link>
  );
}

/** Input de texto canónico: UN estilo para toda la app (border-line, foco de acento,
 *  padding/tipografía de consola). Usa la const `inputCls` cuando necesites
 *  componer (textarea, prefijos, className extra) y `<TextInput>` para el caso común.
 *  Reemplaza las variantes inline sueltas que hoy viven repetidas por el repo. */
export const inputCls =
  "w-full rounded-md border border-line bg-surface px-3 py-2.5 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none";

export function TextInput({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputCls} ${className ?? ""}`} />;
}

/** Elegir un archivo, en español y sin letra diminuta.
 *
 *  El control del sistema pinta "Choose File / No file chosen": en inglés, en
 *  gris chico, y sin decir qué archivo espera. Un dueño que no es técnico no
 *  tiene por qué toparse con eso en su propia consola, y menos cuando lo que
 *  está subiendo es su e.firma.
 *
 *  El input nativo se queda dentro del formulario con su `name` y su `required`,
 *  así que quien lo lea con FormData no se enteró de nada. Lo que cambia es lo
 *  que ve el dueño: un botón que se entiende, el nombre de lo que eligió, y
 *  poder arrastrar el archivo encima. */
export function FilePicker({
  name,
  accept,
  required,
  hint,
  onPick,
}: {
  name: string;
  accept?: string;
  required?: boolean;
  /** Qué archivo se espera, dicho en corto: "Te lo dio el SAT, termina en .cer". */
  hint?: string;
  onPick?: (file: File | null) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [elegido, setElegido] = useState<string | null>(null);
  const [encima, setEncima] = useState(false);

  function usar(file: File | null) {
    setElegido(file?.name ?? null);
    onPick?.(file);
  }

  function soltar(e: React.DragEvent) {
    e.preventDefault();
    setEncima(false);
    const file = e.dataTransfer.files?.[0];
    if (!file || !ref.current) return;
    // Se le pasan al input nativo para que el formulario los mande igual.
    const bolsa = new DataTransfer();
    bolsa.items.add(file);
    ref.current.files = bolsa.files;
    usar(file);
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setEncima(true);
      }}
      onDragLeave={() => setEncima(false)}
      onDrop={soltar}
      className={`flex items-center gap-3 rounded-md border border-dashed px-3 py-2.5 transition-colors ${
        encima ? "border-accent bg-accent-soft" : "border-line-strong bg-surface"
      }`}
    >
      <input
        ref={ref}
        name={name}
        type="file"
        accept={accept}
        required={required}
        className="sr-only"
        onChange={(e) => usar(e.target.files?.[0] ?? null)}
      />
      <SecondaryButton type="button" onClick={() => ref.current?.click()}>
        {elegido ? "Cambiar" : "Elegir archivo"}
      </SecondaryButton>
      <span className={`min-w-0 flex-1 truncate text-apoyo ${elegido ? "text-ink" : "text-ink-3"}`}>
        {elegido ?? hint ?? "o arrástralo aquí"}
      </span>
    </div>
  );
}

/** Variante grande del campo, para el asistente de primer arranque: ahí el campo
 *  es el protagonista de la pantalla y la densidad de consola se siente apretada.
 *  Se usa como clase suelta (no compuesta sobre inputCls) para que no compitan
 *  dos padding/tamaños del mismo utility. */
export const inputLgCls =
  "w-full rounded-lg border border-line bg-surface px-3.5 py-3 text-seccion text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none";

/** Confirmación destructiva no-bloqueante (reemplaza el confirm() nativo, que bloquea
 *  y no es estilizable). Uso:
 *    const { confirm, dialog } = useConfirm();
 *    if (!(await confirm({ title, message, confirmLabel }))) return;
 *  ...y renderiza {dialog} una vez dentro del componente. */
export function useConfirm() {
  const [state, setState] = useState<{
    title?: string;
    message: string;
    confirmLabel: string;
    resolve: (v: boolean) => void;
  } | null>(null);

  const confirm = useCallback(
    (opts: { title?: string; message: string; confirmLabel?: string }) =>
      new Promise<boolean>((resolve) =>
        setState({ confirmLabel: "Eliminar", ...opts, resolve }),
      ),
    [],
  );

  const close = useCallback((v: boolean) => {
    setState((s) => {
      s?.resolve(v);
      return null;
    });
  }, []);

  useEffect(() => {
    if (!state) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
      if (e.key === "Enter") close(true);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [state, close]);

  const dialog = state ? (
    <div
      className="reveal fixed inset-0 z-50 flex items-center justify-center bg-ink/25 px-4"
      onClick={() => close(false)}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-sm rounded-xl border border-line bg-surface p-5 shadow-[0_12px_40px_rgba(13,45,62,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        {state.title && <p className="text-seccion font-semibold text-ink">{state.title}</p>}
        <p className="mt-1.5 text-cuerpo text-ink-2">{state.message}</p>
        <div className="mt-4 flex justify-end gap-2">
          <SecondaryButton onClick={() => close(false)} autoFocus>
            Cancelar
          </SecondaryButton>
          <button
            onClick={() => close(true)}
            className="rounded-md bg-danger px-3.5 py-2 text-cuerpo font-medium text-surface transition-colors hover:opacity-90 active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger"
          >
            {state.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return { confirm, dialog };
}

export const SOURCE_LABEL: Record<string, string> = {
  aiuda: "Creado en aiuda", // alta directa: nació aquí y aiuda es la fuente
  odoo: "Odoo",
  excel: "Excel",
  csv: "CSV",
  shopify: "Shopify",
  woocommerce: "WooCommerce",
  stripe: "Stripe",
  manual: "confirmado por ti",
  banco: "confirmado en banco",
  whatsapp: "WhatsApp",
  denue: "DENUE · INEGI",
  googlecalendar: "Google Calendar",
  custom: "a la medida", // conexión propia; la presencia trae el nombre que le puso el dueño
};

/** Integraciones con logo propio: se muestra en gris sutil junto al dato. */
export const SOURCE_LOGO: Record<string, string> = {
  odoo: "/brand/int/odoo.svg",
  shopify: "/brand/int/shopify.svg",
  woocommerce: "/brand/int/woocommerce.svg",
  stripe: "/brand/int/stripe.png",
  whatsapp: "/brand/int/whatsapp.png",
};

/** Procedencia + verificación: cada dato existe por una razón rastreable.
 *  Si el registro vive en varios sistemas (presencia), se muestran todos y
 *  cada uno te lleva a su sistema (liga directa cuando existe). */
export function SourceBadge({
  source,
  verified,
  presence,
}: {
  source: string;
  verified?: string;
  presence?: Record<string, { ref?: string; url?: string; file?: string; at?: string }>;
}) {
  const ok = verified === "verificada";
  const systems = Object.keys(presence ?? {});
  const list = systems.length > 0 ? systems : [source];
  return (
    <span className={`inline-flex items-center gap-1.5 text-rotulo ${ok ? "text-ok" : "text-ink-3"}`}>
      {list.map((sys, i) => {
        const logo = SOURCE_LOGO[sys];
        const external = presence?.[sys]?.url;
        // Un registro nacido en aiuda no vive en otro sistema: sin liga (una liga
        // a /integraciones aquí mentiría; no hay nada que conectar para verlo).
        if (sys === "aiuda" && !external) {
          return (
            <span
              key={sys}
              title="Nació aquí: aiuda es la fuente de este registro"
              className="inline-flex items-center gap-1"
            >
              <span className="h-1 w-1 rounded-full bg-ink-3/60" />
              {SOURCE_LABEL.aiuda}
              {i < list.length - 1 && <span className="text-ink-3/50">·</span>}
            </span>
          );
        }
        return (
          <a
            key={sys}
            href={external ?? "/integraciones"}
            target={external ? "_blank" : undefined}
            rel={external ? "noreferrer" : undefined}
            title={
              external
                ? `Abrir en ${SOURCE_LABEL[sys] ?? sys}`
                : `Vive en ${SOURCE_LABEL[sys] ?? sys}${ok ? " — verificada" : " — sin verificar"}`
            }
            className="inline-flex items-center gap-1 transition-opacity hover:opacity-70"
          >
            {logo ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img src={logo} alt="" className="h-2.5 w-2.5 opacity-45 grayscale" />
            ) : (
              <span className="h-1 w-1 rounded-full bg-ink-3/60" />
            )}
            {SOURCE_LABEL[sys] ?? sys}
            {i < list.length - 1 && <span className="text-ink-3/50">·</span>}
          </a>
        );
      })}
      {ok && (
        <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none">
          <path
            d="m2.5 6.5 2.5 2.5 4.5-5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </span>
  );
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { key: string; label: string; count?: number }[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="mb-4 flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`-mb-px flex items-center gap-1.5 border-b-2 px-3.5 py-2.5 text-cuerpo font-medium transition-colors ${
            active === t.key
              ? "border-accent text-ink"
              : "border-transparent text-ink-3 hover:text-ink-2"
          }`}
        >
          {t.label}
          {typeof t.count === "number" && (
            <span
              className={`tnum rounded px-1.5 text-sello ${
                active === t.key ? "bg-accent-soft text-accent-ink" : "bg-line/60 text-ink-3"
              }`}
            >
              {t.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <div className="relative w-full max-w-xs">
      <svg
        viewBox="0 0 14 14"
        className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3"
        fill="none"
      >
        <circle cx="6" cy="6" r="4.2" stroke="currentColor" strokeWidth="1.3" />
        <path d="m9.5 9.5 2.7 2.7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-line bg-surface py-2 pl-8 pr-3 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
      />
      {value && (
        <button
          onClick={() => onChange("")}
          aria-label="Limpiar búsqueda"
          className="absolute right-1.5 top-1/2 -translate-y-1/2 px-1 text-seccion leading-none text-ink-3 hover:text-ink"
        >
          &times;
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-xl rounded-lg border border-line-strong bg-surface px-6 py-14 text-center">
      <p className="text-seccion font-semibold text-ink">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-cuerpo text-ink-2">{children}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** Error visible y honesto: dice QUÉ pasó (el detalle en español que manda el
 *  backend) y qué hacer. `retry` pinta el botón de reintentar (pásale el
 *  `refetch` de useApi); sin él, la guía sigue siendo accionable. */
export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  const generico = !message || /^Error \d+$/.test(message);
  const detalle = generico
    ? "El sistema no está disponible en este momento."
    : /[.!?]$/.test(message.trim())
      ? message.trim()
      : `${message.trim()}.`;
  return (
    <div className="mx-auto max-w-xl rounded-lg border border-line bg-surface px-6 py-12 text-center">
      <p className="text-seccion font-semibold text-ink">No pudimos conectar</p>
      <p className="mx-auto mt-2 max-w-md text-cuerpo text-ink-2">
        {detalle} Intenta de nuevo en unos segundos; si sigue igual, avísale a tu
        equipo.
      </p>
      {retry && (
        <div className="mt-4">
          <SecondaryButton onClick={retry}>Reintentar</SecondaryButton>
        </div>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className: string }) {
  return <div className={`skeleton ${className}`} />;
}

/** Fetch con estado de carga/error + refetch. `deps` re-dispara el fetch (ej. tab activa). */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const runIdRef = useRef(0);

  // `silent`: refresca sin encender `loading` (sin flash de skeletons). Para recargar
  // tras una acción cuando la lista YA está en pantalla. Devuelve la promesa para poder
  // encadenar (ej. limpiar un estado local justo cuando el dato nuevo llegó).
  const load = useCallback((silent: boolean) => {
    const runId = ++runIdRef.current;
    if (!silent) setLoading(true);
    // Un fetch colgado no debe dejar la pantalla en skeletons para siempre: a los 12s se
    // resuelve como error visible (ErrorState) en vez de spinner eterno. runId ignora las
    // respuestas que lleguen tarde (deps cambiadas, componente desmontado).
    let timer: ReturnType<typeof setTimeout>;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new Error("La conexión tardó demasiado. Intenta de nuevo.")),
        12000,
      );
    });
    return Promise.race([fetcher(), timeout])
      .then((d) => {
        if (runId !== runIdRef.current) return;
        setData(d as T);
        setError(null);
      })
      .catch((e: Error) => {
        if (runId === runIdRef.current) setError(e.message);
      })
      .finally(() => {
        clearTimeout(timer);
        if (runId === runIdRef.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const refetch = useCallback(() => load(false), [load]);
  const refetchQuiet = useCallback(() => load(true), [load]);

  useEffect(() => {
    load(false);
    return () => {
      runIdRef.current++; // invalida el fetch en curso al desmontar o cambiar deps
    };
  }, [load]);

  return { data, error, loading, refetch, refetchQuiet };
}
