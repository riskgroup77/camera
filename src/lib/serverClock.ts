/**
 * Server soati (ms) — brauzer soati bilan farqi hisobga olingan.
 *
 * WebRTC videoda kadr vaqt belgisi yo'q: tasvir deyarli real vaqtda,
 * ya'ni ekrandagi kadr "hozir"ga teng. Skaner natijalari esa server
 * soatida (capturedAt). Kompyuter soati serverdan bir necha soniya farq
 * qilishi mumkin — shuning uchun farq har skaner javobidan (serverTime)
 * o'lchanadi: so'rov borib-kelish vaqtining yarmi hisobga olinadi va eng
 * qisqa borib-kelishli o'lchov (eng aniq) saqlanadi.
 */

let skewMs = 0;
let bestRoundTripMs = Number.POSITIVE_INFINITY;
let measuredAt = 0;

/** `sentAt`/`receivedAt` — brauzer soati (Date.now()), `serverTime` — epoch soniya. */
export function noteServerTime(serverTime: number | null | undefined, sentAt: number, receivedAt: number): void {
  if (serverTime == null || !Number.isFinite(serverTime)) return;
  const roundTrip = Math.max(0, receivedAt - sentAt);
  // Eski o'lchov 5 daqiqadan keyin yangisi bilan almashadi (soat siljishi).
  const stale = receivedAt - measuredAt > 5 * 60_000;
  if (roundTrip > bestRoundTripMs && !stale) return;
  bestRoundTripMs = roundTrip;
  measuredAt = receivedAt;
  skewMs = serverTime * 1000 - (sentAt + roundTrip / 2);
}

export function serverNow(): number {
  return Date.now() + skewMs;
}

export function resetServerClockForTests(): void {
  skewMs = 0;
  bestRoundTripMs = Number.POSITIVE_INFINITY;
  measuredAt = 0;
}
