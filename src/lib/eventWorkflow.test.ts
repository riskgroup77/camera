import { describe, expect, it } from 'vitest';
import type { AIEvent } from '../types';
import {
  canAssign,
  canTransition,
  isEventUpdate,
  mergeEventUpdate,
  slaInfo,
  statusActions,
} from './eventWorkflow';

function event(overrides: Partial<AIEvent> = {}): AIEvent {
  return {
    id: 'e1',
    timestamp: '2026-09-19 10:00',
    cameraId: 'c1',
    cameraName: 'Koridor',
    building: '1-bino',
    moduleCode: 17,
    moduleName: 'Tartib',
    group: 'D',
    confidence: 60,
    severity: "o'rta",
    status: 'yangi',
    ...overrides,
  };
}

describe('canTransition', () => {
  it('mirrors the server rules', () => {
    expect(canTransition('yangi', 'jarayonda')).toBe(true);
    expect(canTransition('tasdiqlangan', 'hal_qilindi')).toBe(true);
    expect(canTransition('rad_etilgan', 'hal_qilindi')).toBe(false);
    expect(canTransition('tasdiqlangan', 'yangi')).toBe(false);
    expect(canTransition('yangi', 'yangi')).toBe(false);
  });
});

describe('statusActions', () => {
  it('lists the usual next step first and asks for a note only when resolving', () => {
    const actions = statusActions('yangi');
    expect(actions.map((a) => a.target)).toEqual(['jarayonda', 'tasdiqlangan', 'hal_qilindi', 'rad_etilgan']);
    expect(actions.find((a) => a.target === 'hal_qilindi')?.needsNote).toBe(true);
    expect(actions.filter((a) => a.needsNote)).toHaveLength(1);
  });

  it('calls it "reopen" for a closed event', () => {
    const reopen = statusActions('hal_qilindi').find((a) => a.target === 'jarayonda');
    expect(reopen?.label).toBe('Qayta ochish');
    expect(statusActions('jarayonda').find((a) => a.target === 'yangi')?.label).toBe('Navbatga qaytarish');
  });
});

describe('canAssign', () => {
  it('refuses closed and trial events', () => {
    expect(canAssign(event({ status: 'tasdiqlangan' }))).toBe(true);
    expect(canAssign(event({ status: 'hal_qilindi' }))).toBe(false);
    expect(canAssign(event({ status: 'rad_etilgan' }))).toBe(false);
    expect(canAssign(event({ isTrial: true }))).toBe(false);
  });
});

describe('slaInfo', () => {
  const now = new Date('2026-09-19T10:00:00+05:00');

  it('counts down, warns when close and flags overdue', () => {
    expect(slaInfo(event({ dueAt: '2026-09-19T10:45:00+05:00' }), now)).toMatchObject({ state: 'ok', label: '45 daq qoldi' });
    expect(slaInfo(event({ dueAt: '2026-09-19T10:05:00+05:00' }), now).state).toBe('soon');
    expect(slaInfo(event({ status: 'jarayonda', dueAt: '2026-09-19T09:48:00+05:00' }), now)).toMatchObject({
      state: 'overdue',
      label: "Muddati o'tgan: 12 daq",
    });
  });

  it('ignores the deadline once a decision is made or when there is none', () => {
    expect(slaInfo(event({ status: 'hal_qilindi', dueAt: '2026-09-19T09:00:00+05:00' }), now).state).toBe('none');
    expect(slaInfo(event({ dueAt: null }), now).state).toBe('none');
    expect(slaInfo(event({ dueAt: 'yaroqsiz' }), now).state).toBe('none');
  });
});

describe('live updates', () => {
  it('recognises update messages', () => {
    expect(isEventUpdate(event({ kind: 'event_updated' }))).toBe(true);
    expect(isEventUpdate(event())).toBe(false);
  });

  it('replaces the matching row, keeps the comment count when missing and drops the kind', () => {
    const rows = [event({ commentsCount: 3 }), event({ id: 'e2' })];
    const merged = mergeEventUpdate(rows, event({ status: 'jarayonda', commentsCount: null, kind: 'event_updated' }));
    expect(merged[0].status).toBe('jarayonda');
    expect(merged[0].commentsCount).toBe(3);
    expect(merged[0].kind).toBeUndefined();
    expect(merged[1]).toBe(rows[1]);
    expect(mergeEventUpdate(rows, event({ id: 'boshqa' }))).toBe(rows);
  });
});
