import { describe, expect, it } from 'vitest';
import { LATE_RAG, RATE_RAG, rag, ragHint } from './rag';

describe('svetofor', () => {
  it('davomat foizi: yuqori — yashil', () => {
    expect(rag(96)).toBe('yashil');
    expect(rag(90)).toBe('yashil');
    expect(rag(89.9)).toBe('sariq');
    expect(rag(75)).toBe('sariq');
    expect(rag(74.9)).toBe('qizil');
    expect(rag(0)).toBe('qizil');
  });

  it("o'lchanmagan qiymat rangsiz qoladi", () => {
    expect(rag(null)).toBe('yoq');
    expect(rag(undefined)).toBe('yoq');
    expect(rag(Number.NaN)).toBe('yoq');
  });

  it('teskari ko\'rsatkichda kam bo\'lgani yashil (kechikish ulushi)', () => {
    expect(rag(2, LATE_RAG)).toBe('yashil');
    expect(rag(5, LATE_RAG)).toBe('yashil');
    expect(rag(9, LATE_RAG)).toBe('sariq');
    expect(rag(20, LATE_RAG)).toBe('qizil');
  });

  it('izoh chegaralarni yo\'nalishiga qarab yozadi', () => {
    expect(ragHint(RATE_RAG)).toContain('90% va yuqori');
    expect(ragHint(LATE_RAG)).toContain('5% gacha');
  });
});
