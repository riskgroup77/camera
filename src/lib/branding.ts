/** Tashkilot nomi va tizim nomi — boshqa muassasaga o'rnatishda
 *  VITE_ORG_NAME / VITE_SYSTEM_NAME orqali almashtiriladi. */
const env = import.meta.env as Record<string, string | undefined>;

export const branding = {
  /** Qisqa nom (yon panel, sarlavhalar). */
  orgName: env.VITE_ORG_NAME?.trim() || "Farg'ona JSSTI",
  /** To'liq nom (kirish sahifasi). */
  orgFullName: env.VITE_ORG_FULL_NAME?.trim() || "Farg'ona jamoat salomatligi tibbiyot instituti",
  /** Tizim nomi. */
  systemName: env.VITE_SYSTEM_NAME?.trim() || 'Nazorat',
} as const;
