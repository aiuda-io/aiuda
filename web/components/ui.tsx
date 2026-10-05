"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
    <header className="mb-10 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0">
        <h1 className="text-titulo font-semibold text-ink">{title}</h1>
        {subtitle && <p className="mt-2.5 max-w-xl text-cuerpo text-ink-2">{subtitle}</p>}
      </div>
      {right}
    </header>
  );
}

export function BucketPill({ bucket }: { bucket: string }) {
  const meta = BUCKET_META[bucket] ?? { label: bucket, bar: "bg-ink-3" };
  // Un punto y la palabra: el color va solo en la marca, el estado lo dice el texto.
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-rotulo font-medium text-ink-2">
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.bar}`} />
      {meta.label}
    </span>
  );
}

/** Sello de una integración que nadie ha usado todavía con una cuenta real. La
 *  verdad sale del catálogo del servidor (`estrenada`), no de esta pantalla. */
export const SIN_ESTRENAR_NOTA =
  "Está construida, pero todavía nadie la ha usado con una cuenta real.";

export function SinEstrenar() {
  return <Sello title={SIN_ESTRENAR_NOTA}>Sin estrenar</Sello>;
}

/** SELLO: una etiqueta neutra de una o dos palabras que CLASIFICA ("Sin estrenar",
 *  "Borrador", "WhatsApp"). Contorno fino, sin relleno y sin color. Es la única
 *  píldora de la consola: si lo que quieres decir es cómo VA algo, es un `Estado`.
 *  Regla de uso: a lo más un sello por renglón, y nunca uno que repita lo que ya
 *  dice el título de la sección donde está. */
export function Sello({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className="sello">
      {children}
    </span>
  );
}

/** Tonos de un `Estado`. El color va solo en el punto; la palabra es la señal. */
const TONO = {
  neutro: "var(--color-ink-3)",
  ok: "var(--color-ok)",
  aviso: "var(--color-warn)",
  alerta: "var(--color-warn-strong)",
  falla: "var(--color-danger)",
  acento: "var(--color-accent)",
} as const;
export type Tono = keyof typeof TONO;

/** ESTADO: cómo va algo, dicho con una palabra y una marca chica ("Enviado",
 *  "No salió", "Vence hoy"). Sin fondo de color y sin contorno: el punto de 6px
 *  acompaña a la palabra, nunca la sustituye. `fuerte` sube la palabra a tinta
 *  cuando el estado es lo que hay que leer primero en el renglón. */
export function Estado({
  tono = "neutro",
  fuerte,
  title,
  children,
}: {
  tono?: Tono;
  fuerte?: boolean;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      title={title}
      className={`mark ${fuerte ? "font-semibold text-ink" : ""}`}
      style={{ "--mark": TONO[tono] } as React.CSSProperties}
    >
      {children}
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
  sm: "btn-sm",
  md: "",
  /** Superficies de pantalla completa (asistente de primer arranque): el botón
   *  es el objeto principal de la vista y la densidad de consola queda chica. */
  lg: "btn-lg",
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
      className={`btn btn-primary ${BTN_SIZE[size]} ${className ?? ""}`}
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
      className={`btn btn-secondary ${BTN_SIZE[size]} ${className ?? ""}`}
    />
  );
}

/** El botón callado: solo la palabra, con fondo al pasar encima. Para lo que
 *  acompaña a la acción de un renglón o de un diálogo ("Editar", "Rechazar",
 *  "Cancelar") sin competirle. */
export function QuietButton({
  size = "md",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { size?: BtnSize }) {
  return (
    <button
      {...props}
      className={`btn btn-quiet ${BTN_SIZE[size]} ${className ?? ""}`}
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
      className={`btn btn-primary ${BTN_SIZE[size]}`}
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
      className={`btn btn-secondary ${BTN_SIZE[size]}`}
    >
      {children}
    </Link>
  );
}

export function QuietLink({
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
      className={`btn btn-quiet ${BTN_SIZE[size]}`}
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
  "field focus:border-accent focus:outline-none";

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
      className={`flex items-center gap-3 rounded-lg border border-dashed p-2 transition-colors ${
        encima ? "border-accent bg-accent-soft" : "border-field bg-surface"
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
  "field field-lg focus:border-accent focus:outline-none";

/** Confirmación no-bloqueante (reemplaza el confirm() nativo, que bloquea y no es
 *  estilizable). Uso:
 *    const { confirm, dialog } = useConfirm();
 *    if (!(await confirm({ title, message, confirmLabel }))) return;
 *  ...y renderiza {dialog} una vez dentro del componente.
 *  Por defecto es la confirmación de algo que BORRA (botón rojo). Con
 *  `borra: false` confirma una decisión que no destruye nada (botón primario). */
export function useConfirm() {
  const [state, setState] = useState<{
    title?: string;
    message: string;
    confirmLabel: string;
    borra: boolean;
    resolve: (v: boolean) => void;
  } | null>(null);

  const confirm = useCallback(
    (opts: { title?: string; message: string; confirmLabel?: string; borra?: boolean }) =>
      new Promise<boolean>((resolve) =>
        setState({ confirmLabel: "Eliminar", borra: true, ...opts, resolve }),
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
      className="reveal fixed inset-0 z-50 flex items-center justify-center bg-ink/20 px-4"
      onClick={() => close(false)}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-sm rounded-2xl bg-surface p-7 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        {state.title && <p className="text-seccion font-semibold text-ink">{state.title}</p>}
        <p className="mt-2 text-cuerpo text-ink-2">{state.message}</p>
        <div className="mt-6 flex justify-end gap-2">
          <QuietButton onClick={() => close(false)} autoFocus>
            Cancelar
          </QuietButton>
          <button
            onClick={() => close(true)}
            className={`btn ${state.borra ? "btn-danger" : "btn-primary"}`}
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
  denue: "DENUE · INEGI", // conector retirado; rotula los prospectos que ya se cargaron de ahí
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
                : `Vive en ${SOURCE_LABEL[sys] ?? sys}${ok ? ", verificada" : ", sin verificar"}`
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

/** PESTAÑAS de sección: palabras sobre una raya, la activa en tinta.
 *
 *  Dos formas de usarlas, con la misma cara:
 *   - de estado: `onChange` y tú guardas cuál va (filtros de una lista).
 *   - de sección, con query: pásale `hrefFor` y cada pestaña es un enlace de
 *     verdad (`/facturas?vista=pagos`): se puede abrir en otra ventana, compartir
 *     y volver con Atrás. Lee cuál va con `useQueryTab`. */
export function Tabs({
  tabs,
  active,
  onChange,
  hrefFor,
  label,
}: {
  tabs: { key: string; label: string; count?: number }[];
  active: string;
  onChange?: (key: string) => void;
  /** La dirección de cada pestaña. Si viene, las pestañas son enlaces. */
  hrefFor?: (key: string) => string;
  /** Nombre del grupo para lectores de pantalla ("Vistas de Cartera"). */
  label?: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="tabs mb-8">
      {tabs.map((t) => {
        const on = active === t.key;
        const dentro = (
          <>
            {t.label}
            {typeof t.count === "number" && (
              <span className="tnum text-apoyo font-medium text-ink-3">{t.count}</span>
            )}
          </>
        );
        return hrefFor ? (
          <Link
            key={t.key}
            href={hrefFor(t.key)}
            role="tab"
            aria-selected={on}
            scroll={false}
            onClick={() => onChange?.(t.key)}
            className="tab"
          >
            {dentro}
          </Link>
        ) : (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange?.(t.key)}
            className="tab"
          >
            {dentro}
          </button>
        );
      })}
    </div>
  );
}

/** La pestaña que manda la dirección: `?vista=pagos`, `?seccion=ia`.
 *
 *    const [vista, hrefFor] = useQueryTab("vista", ["facturas", "promesas", "pagos"]);
 *    <Tabs tabs={…} active={vista} hrefFor={hrefFor} />
 *
 *  La primera llave es la de fábrica y su dirección va sin query (`/facturas`).
 *  Un valor que no está en la lista cae en la de fábrica, no en una pantalla en
 *  blanco. Los demás parámetros de la dirección se conservan.
 *  OJO: usa `useSearchParams`, así que en el export estático el componente que lo
 *  llame va dentro de `<Suspense>`. */
export function useQueryTab<K extends string>(
  param: string,
  keys: readonly K[],
): [K, (key: string) => string, (key: K) => void] {
  const pathname = usePathname();
  const router = useRouter();
  const params = useSearchParams();
  const raw = params.get(param);
  const active = (keys as readonly string[]).includes(raw ?? "") ? (raw as K) : keys[0];
  const actual = params.toString();

  const hrefFor = useCallback(
    (key: string) => {
      const next = new URLSearchParams(actual);
      if (key === keys[0]) next.delete(param);
      else next.set(param, key);
      const q = next.toString();
      return q ? `${pathname}?${q}` : pathname;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [actual, pathname, param, keys[0]],
  );
  // Para cambiar de pestaña desde código (tras guardar, por ejemplo).
  const go = useCallback(
    (key: K) => router.replace(hrefFor(key), { scroll: false }),
    [router, hrefFor],
  );

  return [active, hrefFor, go];
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
        className="pointer-events-none absolute left-3.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3"
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
        className="field pl-10 pr-8"
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
    <div className="mx-auto max-w-xl px-6 py-24 text-center">
      <p className="text-seccion font-semibold text-ink">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-cuerpo text-ink-2">{children}</p>
      {action && <div className="mt-7">{action}</div>}
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
    <div className="mx-auto max-w-xl px-6 py-20 text-center">
      <p className="text-seccion font-semibold text-ink">No pudimos conectar</p>
      <p className="mx-auto mt-2 max-w-md text-cuerpo text-ink-2">
        {detalle} Intenta de nuevo en unos segundos; si sigue igual, avísale a tu
        equipo.
      </p>
      {retry && (
        <div className="mt-6">
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
