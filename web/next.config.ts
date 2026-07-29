import type { NextConfig } from "next";

// Dos modos de build:
// - dev/`next start`: la consola habla con el API vía /api/* (rewrite same-origin).
// - NEXT_EXPORT=1: export ESTÁTICO (out/) que FastAPI sirve en el mismo origen
//   que el API — ahí no hay rewrites y el cliente llama /v1 directo
//   (NEXT_PUBLIC_API_URL=""). Es el build que se empaqueta en el wheel.
const API_PROXY_URL = process.env.API_PROXY_URL ?? "http://localhost:8000";
const EXPORT = process.env.NEXT_EXPORT === "1";

const nextConfig: NextConfig = {
  // Sin optimizador de imágenes: los avatares y logos son chicos y así
  // renderizan siempre (local y deploy), sin depender de /_next/image ni sharp.
  images: { unoptimized: true },
  // Worktrees de agentes con node_modules por SYMLINK: Turbopack no resuelve
  // fuera de su raíz, así que se le pasa el ancestro común por env (documentado
  // en next/dist/docs → turbopack.md). Sin la variable, nada cambia.
  ...(process.env.TURBOPACK_ROOT ? { turbopack: { root: process.env.TURBOPACK_ROOT } } : {}),
  ...(EXPORT
    ? { output: "export" as const }
    : {
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: `${API_PROXY_URL}/:path*`,
            },
          ];
        },
      }),
};

export default nextConfig;
