/**
 * Backend integratsiyasi uchun markazlashgan konfiguratsiya.
 * Qiymatlar .env.local (VITE_ prefiksli) dan olinadi — ko'ring .env.example.
 * Hozircha bo'sh bo'lsa, tegishli funksiyalar (apiClient, realtime, video)
 * "backend ulanmagan" holatiga qaytadi va buni UI'da ochiq ko'rsatadi.
 */
export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '',
  realtimeUrl: import.meta.env.VITE_REALTIME_URL || '',
  streamGatewayUrl: import.meta.env.VITE_STREAM_GATEWAY_URL || '',
} as const;

export const isBackendConfigured = Boolean(config.apiBaseUrl);
