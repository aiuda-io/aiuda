"use client";

import Link from "next/link";

export type Paso = {
  key: "ia" | "cartera" | "ayudante";
  titulo: string;
  texto: string;
  boton: string;
  href: string;
};

const PASOS: Record<Paso["key"], Paso> = {
  ia: {
    key: "ia",
    titulo: "Tu IA",
    texto: "Es la que redacta los mensajes. Sin ella tus ayudantes no pueden escribir nada.",
    boton: "Conectar tu IA",
    href: "/configuracion?seccion=ia",
  },
  cartera: {
    key: "cartera",
    titulo: "Tu cartera",
    texto: "Sube tu Excel o conecta tu sistema para ver quién te debe y cuánto.",
    boton: "Traer tu cartera",
    href: "/configuracion?seccion=conexiones",
  },
  ayudante: {
    key: "ayudante",
    titulo: "Tu ayudante",
    texto: "Lee tu cartera, redacta los recordatorios y espera tu aprobación antes de enviar.",
    boton: "Crear tu ayudante",
    href: "/ayudantes",
  },
};

/** Qué falta para que Hoy tenga trabajo, en el orden en que se resuelve. */
export function pasosQueFaltan(hay: { ia: boolean; cartera: boolean; ayudante: boolean }): Paso[] {
  return (["ia", "cartera", "ayudante"] as const).filter((k) => !hay[k]).map((k) => PASOS[k]);
}

/** Hoy sin nada que enseñar: solo los pasos que faltan, cada uno con su botón. El
 *  primero es el que sigue, así que es el único botón relleno de color. */
export function PasosQueFaltan({ pasos }: { pasos: Paso[] }) {
  return (
    <section className="max-w-2xl">
      <h2 className="text-seccion font-semibold text-ink">
        {pasos.length === 1 ? "Te falta un paso" : `Te faltan ${pasos.length} pasos`}
      </h2>
      <p className="mt-1 text-cuerpo text-ink-2">
        Cuando estén listos, aquí aparece lo que tu ayudante redactó para que lo apruebes.
      </p>
      <ol className="mt-4">
        {pasos.map((p, i) => (
          <li
            key={p.key}
            className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-line py-5 first:border-t-0"
          >
            <div className="min-w-0 flex-1 basis-64">
              <p className="text-cuerpo font-semibold text-ink">{p.titulo}</p>
              <p className="mt-0.5 text-cuerpo text-ink-2">{p.texto}</p>
            </div>
            <Link href={p.href} className={`btn ${i === 0 ? "btn-primary" : "btn-secondary"}`}>
              {p.boton}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Hay trabajo en pantalla pero falta algo: una línea, no un bloque. */
export function AvisoFaltantes({ pasos }: { pasos: Paso[] }) {
  if (pasos.length === 0) return null;
  return (
    <p className="mt-6 text-cuerpo text-ink-2">
      Todavía falta:{" "}
      {pasos.map((p, i) => (
        <span key={p.key}>
          {i > 0 && ", "}
          <Link
            href={p.href}
            className="font-medium text-accent-ink underline-offset-2 hover:underline"
          >
            {p.boton}
          </Link>
        </span>
      ))}
      .
    </p>
  );
}
