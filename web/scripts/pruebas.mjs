// Pruebas de lo que la consola calcula sin pantalla (hoy: la lectura de fechas).
// Corre con `npm test` y antes de cada export, así que entra en el gate.
//
// No hay corredor de pruebas en web/: se transpila el módulo con el TypeScript que ya
// trae el proyecto y se afirma con node:assert. La zona se fija a la de México ANTES
// de crear cualquier fecha, porque el defecto que esto cuida solo se ve fuera de UTC.
process.env.TZ = "America/Mexico_City";

import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const raiz = join(dirname(fileURLToPath(import.meta.url)), "..");

async function cargar(relativo) {
  const fuente = readFileSync(join(raiz, relativo), "utf8");
  const { outputText } = ts.transpileModule(fuente, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  const carpeta = mkdtempSync(join(tmpdir(), "aiuda-pruebas-web-"));
  const archivo = join(carpeta, "modulo.mjs");
  writeFileSync(archivo, outputText);
  try {
    return await import(pathToFileURL(archivo).href);
  } finally {
    rmSync(carpeta, { recursive: true, force: true });
  }
}

const f = await cargar("lib/format.ts");
let corridas = 0;
function prueba(nombre, fn) {
  try {
    fn();
    corridas += 1;
  } catch (e) {
    console.error(`FALLA: ${nombre}\n${e.message}`);
    process.exit(1);
  }
}

// El reloj se congela: 5 de octubre de 2026, 10:30 de la mañana en México (16:30 UTC).
const AHORA = Date.UTC(2026, 9, 5, 16, 30, 0);
const RelojReal = Date.now;
Date.now = () => AHORA;
const FechaReal = Date;
globalThis.Date = class extends FechaReal {
  constructor(...args) {
    if (args.length === 0) super(AHORA);
    else super(...args);
  }
  static now() {
    return AHORA;
  }
};

prueba("una hora sin zona del servidor es UTC, no hora local", () => {
  // El servidor guardó 16:11:08 UTC: en México son las 10:11.
  const d = f.instante("2026-10-05T16:11:08");
  assert.equal(d.toISOString(), "2026-10-05T16:11:08.000Z");
  assert.equal(d.getHours(), 10);
});

prueba("con microsegundos y con espacio en vez de T también es UTC", () => {
  assert.equal(f.instante("2026-10-05T16:11:08.123456").getHours(), 10);
  assert.equal(f.instante("2026-10-05 16:11:08").getHours(), 10);
});

prueba("una hora que ya trae zona se respeta", () => {
  assert.equal(f.instante("2026-10-05T16:11:08Z").getHours(), 10);
  assert.equal(f.instante("2026-10-05T16:11:08+00:00").getHours(), 10);
  assert.equal(f.instante("2026-10-05T10:11:08-06:00").getHours(), 10);
});

prueba("una fecha sola es ese día en el calendario local, no el anterior", () => {
  const d = f.instante("2026-05-18");
  assert.equal(d.getDate(), 18);
  assert.equal(d.getHours(), 0);
  assert.equal(f.fechaDM("2026-05-18"), "18 may");
  assert.equal(f.fecha("2026-05-18"), "18 may 2026");
});

prueba("algo de hace 19 minutos dice hace 19 min, no hace un momento", () => {
  // Antes: leída como local quedaba seis horas en el futuro y decía "hace un momento".
  assert.equal(f.haceTiempo("2026-10-05T16:11:00"), "hace 19 min");
  assert.equal(f.haceTiempo("2026-10-05T14:30:00"), "hace 2 h");
  assert.equal(f.haceTiempo("2026-10-03T16:30:00"), "hace 2 d");
});

prueba("la fecha con hora sale en la hora de quien mira", () => {
  assert.match(f.fechaHora("2026-10-05T16:11:08"), /10:11/);
  assert.match(f.hoyOFecha("2026-10-05T16:11:08"), /^Hoy, 10:11/);
});

prueba("lo enviado ayer en la noche de México no cuenta como de hoy", () => {
  // 04:30 UTC del día 5 son las 22:30 del día 4 en México.
  assert.equal(f.esDeHoy("2026-10-05T04:30:00"), false);
  assert.equal(f.esDeHoy("2026-10-05T16:11:08"), true);
  // Y lo de hoy en la tarde (23:30 UTC = 17:30 local) sí es de hoy.
  assert.equal(f.esDeHoy("2026-10-05T23:30:00"), true);
});

prueba("una fecha se escribe igual en toda la consola: 2 oct, 5 oct 2026", () => {
  assert.equal(f.fechaDM("2026-10-02"), "2 oct");
  assert.equal(f.fecha("2026-10-05"), "5 oct 2026");
  assert.equal(f.fechaHora("2026-10-05T16:11:08"), "5 oct, 10:11");
  assert.equal(f.hoyOFecha("2026-10-04T16:11:08"), "4 oct, 10:11");
});

prueba("la hora de una cita es de reloj: no se corre", () => {
  assert.equal(f.deReloj("2026-10-06T10:00:00").getHours(), 10);
});

prueba("lo que no es fecha no truena", () => {
  assert.equal(f.instante(null), null);
  assert.equal(f.instante(""), null);
  assert.equal(f.instante("no es fecha"), null);
  assert.equal(f.fechaHora(undefined), "·");
  assert.equal(f.haceTiempo("0001-01-01T00:00:00"), "·");
});

globalThis.Date = FechaReal;
Date.now = RelojReal;
console.log(`pruebas de la consola: ${corridas} en verde`);
