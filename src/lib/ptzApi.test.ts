import { describe, expect, it } from 'vitest';
import { clampVelocity, createPtzCommandQueue, type PtzCommand } from './ptzApi';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe('PTZ buyruqlar navbati', () => {
  it('bir vaqtda bitta so\'rov, oraliq buyruqlar tashlanadi, oxirgisi yuboriladi', async () => {
    const sent: PtzCommand[] = [];
    const gates: Array<() => void> = [];
    const queue = createPtzCommandQueue(
      (command) => {
        sent.push(command);
        const gate = deferred();
        gates.push(gate.resolve);
        return gate.promise;
      },
      () => {},
    );
    queue.push({ kind: 'move', velocity: { pan: 1, tilt: 0, zoom: 0 } });
    queue.push({ kind: 'move', velocity: { pan: -1, tilt: 0, zoom: 0 } });
    queue.push({ kind: 'stop' });
    expect(sent).toHaveLength(1);
    gates[0]();
    await new Promise((r) => setTimeout(r, 0));
    expect(sent.map((c) => c.kind)).toEqual(['move', 'stop']);
    gates[1]();
    await new Promise((r) => setTimeout(r, 0));
    expect(queue.busy).toBe(false);
  });

  it('xato navbatni to\'xtatmaydi', async () => {
    const errors: unknown[] = [];
    const sent: string[] = [];
    let first = true;
    const queue = createPtzCommandQueue(
      async (command) => {
        sent.push(command.kind);
        if (first) {
          first = false;
          throw new Error('kamera javob bermadi');
        }
      },
      (err) => errors.push(err),
    );
    queue.push({ kind: 'move', velocity: { pan: 0.5, tilt: 0, zoom: 0 } });
    queue.push({ kind: 'stop' });
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
    expect(sent).toEqual(['move', 'stop']);
    expect(errors).toHaveLength(1);
  });

  it('tezlik chegaralanadi', () => {
    expect(clampVelocity(2)).toBe(1);
    expect(clampVelocity(-3)).toBe(-1);
    expect(clampVelocity(Number.NaN)).toBe(0);
    expect(clampVelocity(0.12345)).toBe(0.123);
  });
});
