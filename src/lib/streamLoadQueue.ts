/** HLS oqimlar navbati — bir vaqtda max 4 ta parallel ulanish. */
const MAX_CONCURRENT = 4;
let active = 0;
const waiters: Array<() => void> = [];

export function acquireStreamSlot(): Promise<void> {
  if (active < MAX_CONCURRENT) {
    active += 1;
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    waiters.push(() => {
      active += 1;
      resolve();
    });
  });
}

export function releaseStreamSlot(): void {
  active = Math.max(0, active - 1);
  const next = waiters.shift();
  if (next) next();
}

export function streamQueueStats(): { active: number; waiting: number } {
  return { active, waiting: waiters.length };
}
