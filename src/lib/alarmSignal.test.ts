import { afterEach, describe, expect, it, vi } from 'vitest';
import { isAlarm, setAlarmSoundEnabled, signalAlarm } from './alarmSignal';
import type { AIEvent } from '../types';

function event(overrides: Partial<AIEvent> = {}): AIEvent {
  return {
    id: `e-${Math.random()}`,
    timestamp: '2026-09-24 12:00',
    cameraId: 'c1',
    cameraName: 'Asosiy kirish',
    building: 'A',
    moduleCode: 23,
    moduleName: "Yong'in",
    group: 'A',
    confidence: 90,
    severity: 'yuqori',
    status: 'yangi',
    ...overrides,
  } as AIEvent;
}

afterEach(() => setAlarmSoundEnabled(true));

describe('isAlarm', () => {
  it('faqat yangi, yuqori darajali va sinovda bo‘lmagan hodisa', () => {
    expect(isAlarm(event())).toBe(true);
    expect(isAlarm(event({ severity: "o'rta" }))).toBe(false);
    expect(isAlarm(event({ isTrial: true }))).toBe(false);
    expect(isAlarm(event({ status: 'tasdiqlangan' }))).toBe(false);
  });
});

describe('signalAlarm', () => {
  it('bir hodisa ikki kanaldan kelsa ham bir marta', () => {
    setAlarmSoundEnabled(false);
    const e = event();
    expect(signalAlarm(e)).toBe(true);
    expect(signalAlarm(e)).toBe(false);
  });

  it('holati o‘zgargan eski hodisa signal bermaydi', () => {
    setAlarmSoundEnabled(false);
    expect(signalAlarm({ ...event(), kind: 'event_updated' })).toBe(false);
  });

  it('ovoz o‘chirilgan bo‘lsa AudioContext yaratilmaydi', () => {
    setAlarmSoundEnabled(false);
    const ctor = vi.fn();
    vi.stubGlobal('AudioContext', ctor);
    signalAlarm(event());
    expect(ctor).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
