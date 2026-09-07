/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Origin of the backend, e.g. https://itinerary-backend.onrender.com.
   * Unset in development, where Vite proxies /api to :8420 instead.
   */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
