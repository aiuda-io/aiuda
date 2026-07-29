import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // La consola carga y reinicia formularios al abrir paneles; esos efectos
      // sincronizan estado con una fuente externa (API, ruta o diálogo).
      "react-hooks/set-state-in-effect": "off",
      // useApi acepta dependencias de quien lo llama, igual que useEffect.
      "react-hooks/use-memo": "off",
      // Ningún tamaño de letra clavado en píxeles. Llegamos a tener 1012 de
      // estos, repartidos en 55 archivos, y el resultado era una consola que el
      // dueño de una taquería no podía leer. La escala vive en globals.css y la
      // pantalla pide el papel del texto, no un número (ver DESIGN.md).
      "no-restricted-syntax": [
        "error",
        {
          selector: "Literal[value=/text-\\[[0-9.]+px\\]/]",
          message:
            "Sin tamaños de letra clavados: usa la escala semántica (text-cifra / titulo / seccion / cuerpo / apoyo / rotulo / sello). Ver web/DESIGN.md.",
        },
        {
          selector: "TemplateElement[value.raw=/text-\\[[0-9.]+px\\]/]",
          message:
            "Sin tamaños de letra clavados: usa la escala semántica (text-cifra / titulo / seccion / cuerpo / apoyo / rotulo / sello). Ver web/DESIGN.md.",
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
