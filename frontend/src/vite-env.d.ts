/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BACKEND_AUTH_SECRET: string;
  // If there are other environment variables, continue to add them here
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}