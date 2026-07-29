/**
 * El manual del dueño, servido por el propio aiuda.
 *
 * Toma los documentos de `docs/` (los de siempre, los que se leen en GitHub) y
 * los deja como páginas en `web/public/manual/`, que el export de Next copia a
 * `out/` y FastAPI sirve en el mismo puerto que la consola. Resultado: el enlace
 * "Manual" de la consola abre documentación que viaja DENTRO de la app y
 * funciona sin internet, que es justo lo que aiuda promete.
 *
 * Una sola fuente: el markdown de `docs/`. Aquí no se escribe contenido, solo se
 * le pone forma. Si un documento miente, se arregla allá.
 *
 * Nada de fuentes ni scripts de afuera: una página que necesita internet para
 * verse bien no sirve para explicar por qué algo no funciona.
 *
 *   node scripts/manual.mjs      (lo corre solo antes de dev/build/export)
 */

import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { marked } from "marked";

const AQUI = dirname(fileURLToPath(import.meta.url));
const RAIZ = join(AQUI, "..", "..");
const ORIGEN = join(RAIZ, "docs");
const DESTINO = join(AQUI, "..", "public", "manual");
const REPO = "https://github.com/aiuda-io/aiuda";

// El orden es el del dueño, no el alfabético: primero instalar, al final lo
// experimental. La descripción es lo que se lee en la portada.
const PAGINAS = [
  {
    archivo: "INSTALAR.md",
    slug: "instalar",
    corto: "Instalar",
    desc: "Poner aiuda en tu computadora y abrirlo la primera vez.",
  },
  {
    archivo: "IA.md",
    slug: "ia",
    corto: "Tu IA",
    desc: "Conectar el Claude Code o Codex que ya tienes, una llave, tu suscripción o un modelo local.",
  },
  {
    archivo: "APARATOS.md",
    slug: "aparatos",
    corto: "Tu teléfono",
    desc: "Dejar entrar tu celular y el de quien trabaja contigo, sin salir de tu WiFi.",
  },
  {
    archivo: "DATOS.md",
    slug: "datos",
    corto: "Tus datos",
    desc: "Dónde vive todo, cómo respaldarlo y cómo borrarlo sin dejar rastro.",
  },
  {
    archivo: "SAT.md",
    slug: "sat",
    corto: "SAT y CFDI",
    desc: "Bóveda fiscal, e.firma y descarga de CFDI para hasta tres RFCs.",
  },
  {
    archivo: "PROBLEMAS.md",
    slug: "problemas",
    corto: "Cuando algo falla",
    desc: "Lo que más se atora, con su arreglo.",
  },
  {
    archivo: "CUA.md",
    slug: "cua",
    corto: "Portales sin API",
    desc: "El navegador que opera el SAT o tu banco por ti. Lo más experimental que hay aquí.",
  },
];

const porArchivo = new Map(PAGINAS.map((p) => [p.archivo.toUpperCase(), p]));

/** Un enlace del markdown, apuntando a donde sirva dentro del manual. */
function enlace(href) {
  if (/^(https?:|mailto:|#)/.test(href)) return { href, fuera: /^https?:/.test(href) };
  const [ruta, ancla = ""] = href.split("#");
  if (!ruta.toLowerCase().endsWith(".md")) return { href, fuera: false };
  const nombre = ruta.split("/").pop().toUpperCase();
  const pagina = porArchivo.get(nombre);
  if (pagina && !ruta.startsWith("../")) {
    return { href: `${pagina.slug}.html${ancla ? `#${ancla}` : ""}`, fuera: false };
  }
  // Lo que no viaja en el manual (SECURITY.md, ARCHITECTURE.md) vive en GitHub.
  const enRepo = ruta.startsWith("../") ? ruta.slice(3) : `docs/${ruta}`;
  return { href: `${REPO}/blob/main/${enRepo}`, fuera: true };
}

function reescribirEnlaces(html) {
  return html.replace(/href="([^"]+)"/g, (_, href) => {
    const r = enlace(href);
    return r.fuera
      ? `href="${r.href}" target="_blank" rel="noreferrer"`
      : `href="${r.href}"`;
  });
}

const ESTILO = `
:root{
  --paper: oklch(0.99 0.004 245);
  --surface: oklch(0.972 0.005 245);
  --card: oklch(0.997 0.002 245);
  --ink: oklch(0.26 0.045 250);
  --ink-muted: oklch(0.47 0.03 250);
  --ink-faint: oklch(0.585 0.022 250);
  --brand: oklch(0.52 0.115 238);
  --brand-ink: oklch(0.41 0.105 242);
  --brand-soft: oklch(0.955 0.026 238);
  --line: oklch(0.915 0.008 250);
  --line-strong: oklch(0.865 0.012 250);
  --body: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color-scheme: light;
}
*{ box-sizing:border-box; margin:0 }
body{
  font-family:var(--body); background:var(--paper); color:var(--ink);
  font-size:16px; line-height:1.65; -webkit-font-smoothing:antialiased;
}
a{ color:var(--brand-ink); text-underline-offset:2px }
a:hover{ color:var(--brand) }

.barra{ border-bottom:1px solid var(--line); background:var(--card) }
.barra .caja{ display:flex; align-items:center; gap:16px; height:56px }
.marca{ font-weight:700; font-size:1.05rem; letter-spacing:-0.02em; text-decoration:none; color:var(--ink) }
.marca span{ color:var(--brand) }
.etiqueta{
  font-family:var(--mono); font-size:.66rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-faint); border:1px solid var(--line); border-radius:999px; padding:4px 10px;
}
.volver{ margin-left:auto; font-size:.9rem; text-decoration:none }

.caja{ width:min(1040px, calc(100% - 40px)); margin-inline:auto }
.hoja{ display:grid; grid-template-columns:210px minmax(0,1fr); gap:44px; padding:38px 0 72px }
@media (max-width:820px){ .hoja{ grid-template-columns:1fr; gap:26px; padding-top:26px } }

nav.indice{ align-self:start; position:sticky; top:24px }
@media (max-width:820px){ nav.indice{ position:static } }
nav.indice p{
  font-family:var(--mono); font-size:.66rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-faint); margin-bottom:10px;
}
nav.indice a{
  display:block; padding:6px 10px; border-radius:6px; text-decoration:none;
  color:var(--ink-muted); font-size:.92rem;
}
nav.indice a:hover{ background:var(--surface); color:var(--ink) }
nav.indice a[aria-current]{ background:var(--brand-soft); color:var(--brand-ink); font-weight:600 }

article{ max-width:70ch }
article h1{ font-size:2rem; line-height:1.15; letter-spacing:-0.025em; margin-bottom:22px }
article h2{ font-size:1.28rem; letter-spacing:-0.015em; margin:38px 0 12px; padding-top:20px; border-top:1px solid var(--line) }
article h3{ font-size:1.03rem; margin:26px 0 8px }
article p, article ul, article ol, article table, article pre, article blockquote{ margin-bottom:16px }
article ul, article ol{ padding-left:22px }
article li{ margin-bottom:6px }
article li > ul, article li > ol{ margin:6px 0 }
article strong{ font-weight:650 }
article hr{ border:0; border-top:1px solid var(--line); margin:32px 0 }

code{
  font-family:var(--mono); font-size:.86em; background:var(--surface);
  border:1px solid var(--line); border-radius:4px; padding:.1em .34em;
}
pre{
  background:var(--surface); border:1px solid var(--line); border-radius:8px;
  padding:14px 16px; overflow-x:auto;
}
pre code{ background:none; border:0; padding:0; font-size:.84rem; line-height:1.6 }

table{ border-collapse:collapse; width:100%; font-size:.93rem; display:block; overflow-x:auto }
th, td{ border:1px solid var(--line); padding:8px 12px; text-align:left; vertical-align:top }
th{ background:var(--surface); font-weight:600 }

.portada-lista{ list-style:none; padding:0; margin:0 }
.portada-lista li{ margin-bottom:10px }
.portada-lista a{
  display:block; border:1px solid var(--line); border-radius:10px; padding:14px 16px;
  background:var(--card); text-decoration:none; color:inherit;
}
.portada-lista a:hover{ border-color:var(--line-strong); background:var(--surface) }
.portada-lista b{ display:block; font-size:1rem; color:var(--ink) }
.portada-lista span{ display:block; font-size:.9rem; color:var(--ink-muted); margin-top:2px }

footer{ border-top:1px solid var(--line); background:var(--card) }
footer .caja{ padding:22px 0; font-size:.85rem; color:var(--ink-faint) }
footer a{ color:var(--ink-muted) }
`;

function pagina({ titulo, slug, cuerpo }) {
  const indice = PAGINAS.map(
    (p) =>
      `<a href="${p.slug}.html"${p.slug === slug ? ' aria-current="page"' : ""}>${p.corto}</a>`,
  ).join("\n        ");
  return `<!doctype html>
<html lang="es-MX">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${slug === "index" ? "Manual de aiuda" : `${titulo} · Manual de aiuda`}</title>
<meta name="robots" content="noindex" />
<style>${ESTILO}</style>
</head>
<body>
  <header class="barra">
    <div class="caja">
      <a class="marca" href="index.html">aiuda<span>.</span></a>
      <span class="etiqueta">Manual</span>
      <a class="volver" href="/">Volver a la consola</a>
    </div>
  </header>

  <div class="caja hoja">
    <nav class="indice">
      <p>Manual</p>
      <a href="index.html"${slug === "index" ? ' aria-current="page"' : ""}>Portada</a>
      ${indice}
    </nav>
    <article>
${cuerpo}
    </article>
  </div>

  <footer>
    <div class="caja">
      Este manual viaja dentro de aiuda y funciona sin internet. El mismo texto
      está en <a href="${REPO}/tree/main/docs" target="_blank" rel="noreferrer">GitHub</a>.
      <br />Un proyecto de <a href="https://hanova.mx" target="_blank" rel="noreferrer">Hanova Consulting</a>.
    </div>
  </footer>
</body>
</html>
`;
}

const PORTADA = `<h1>Manual de aiuda</h1>
<p>Para el dueño del negocio. Está escrito en español y sin tecnicismos: donde
haga falta la terminal, se dice y se puede saltar.</p>
<ul class="portada-lista">
${PAGINAS.map(
  (p) =>
    `  <li><a href="${p.slug}.html"><b>${p.corto}</b><span>${p.desc}</span></a></li>`,
).join("\n")}
</ul>
<p>aiuda corre en esta computadora. Nada de lo que ves aquí se consultó por
internet: estas páginas vienen dentro de la app.</p>`;

async function main() {
  await rm(DESTINO, { recursive: true, force: true });
  await mkdir(DESTINO, { recursive: true });

  for (const p of PAGINAS) {
    const md = await readFile(join(ORIGEN, p.archivo), "utf8");
    const titulo = (md.match(/^#\s+(.+)$/m) || [, p.corto])[1].trim();
    const cuerpo = reescribirEnlaces(marked.parse(md, { async: false }));
    await writeFile(join(DESTINO, `${p.slug}.html`), pagina({ titulo, slug: p.slug, cuerpo }));
  }

  await writeFile(
    join(DESTINO, "index.html"),
    pagina({ titulo: "Manual", slug: "index", cuerpo: PORTADA }),
  );

  console.log(`manual: ${PAGINAS.length + 1} páginas en public/manual/`);
}

await main();
