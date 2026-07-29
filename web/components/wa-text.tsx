import { type ReactNode } from "react";

// Cero emojis es regla dura del producto: red de seguridad sobre cualquier texto que
// muestre la consola (recordatorios viejos pueden traerlos).
const EMOJI_RE =
  /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F1E6}-\u{1F1FF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\u{FE00}-\u{FE0F}\u{200D}\u{24C2}]/gu;

function stripEmojis(s: string): string {
  return s.replace(EMOJI_RE, "");
}

// Formato de WhatsApp: *negrita*, _itálica_, ~tachado~. En la consola se RENDERIZA
// como lo verá el cliente, en vez de mostrar los asteriscos crudos.
function renderInline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const inner = tok.slice(1, -1);
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("*")) out.push(<strong key={key} className="font-semibold">{inner}</strong>);
    else if (tok.startsWith("_")) out.push(<em key={key}>{inner}</em>);
    else out.push(<s key={key}>{inner}</s>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Texto de WhatsApp renderado como lo verá el cliente: negritas/itálicas reales,
 *  sin emojis, conservando saltos de línea. */
export function WaText({ children, className }: { children: string; className?: string }) {
  const clean = stripEmojis(children);
  const lines = clean.split("\n");
  return (
    <p className={className}>
      {lines.map((line, i) => (
        <span key={i}>
          {renderInline(line, String(i))}
          {i < lines.length - 1 && <br />}
        </span>
      ))}
    </p>
  );
}
