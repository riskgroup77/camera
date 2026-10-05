import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBoard, boardRag, type BoardItem } from './board';
import { RATE_RAG } from '../../ui/rag';

const item = (over: Partial<BoardItem> = {}): BoardItem => ({
  id: 'u1', name: 'Ichki kasalliklar', value: 92, unit: '%',
  detail: '142/160 keldi', headcount: 160, ...over,
});

describe('boardRag', () => {
  it('foizga svetofor qo\'yadi', () => {
    expect(boardRag(item({ value: 92 }), RATE_RAG)).toBe('yashil');
    expect(boardRag(item({ value: 80 }), RATE_RAG)).toBe('sariq');
    expect(boardRag(item({ value: 40 }), RATE_RAG)).toBe('qizil');
  });

  it("foiz bo'lmagan ko'rsatkichga hukm chiqarmaydi", () => {
    // "12 ta kechikish" yaxshimi yomonmi — bo'linma kattaligisiz noma'lum.
    expect(boardRag(item({ value: 12, unit: 'ta' }), RATE_RAG)).toBe('yoq');
  });

  it("o'lchanmagan qiymat rangsiz", () => {
    expect(boardRag(item({ value: null }), RATE_RAG)).toBe('yoq');
  });
});

describe('StatusBoard', () => {
  it('nom, qiymat va harfni chizadi', () => {
    render(<StatusBoard items={[item()]} />);
    expect(screen.getByText('Ichki kasalliklar')).toBeInTheDocument();
    expect(screen.getByText('92%')).toBeInTheDocument();
    // Rang yolg'iz qolmaydi: harf ham bo'lishi shart.
    expect(screen.getByText('Y')).toBeInTheDocument();
  });

  it('bosilganda bo\'linmani ochadi', () => {
    const onOpen = vi.fn();
    render(<StatusBoard items={[item()]} onOpen={onOpen} />);
    screen.getByRole('button').click();
    expect(onOpen).toHaveBeenCalledWith('u1');
  });

  it("ro'yxat bo'sh bo'lsa sababini aytadi", () => {
    render(<StatusBoard items={[]} />);
    expect(screen.getByText(/bo'linma ma'lumoti yo'q/i)).toBeInTheDocument();
  });
});
