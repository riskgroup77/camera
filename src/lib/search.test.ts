import { describe, expect, it } from 'vitest';
import { highlight, loadRecent, matchText, normalize, pushRecent, rankItems, RECENT_KEY } from './search';

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  };
}

describe('normalize', () => {
  it('unifies apostrophes, spaces and case', () => {
    expect(normalize('O‘qituvchilar')).toBe("o'qituvchilar");
    expect(normalize('  Oʻquv   BOʻLIMI ')).toBe("o'quv bo'limi");
  });
});

describe('matchText', () => {
  it('ranks exact > prefix > word start > substring > fuzzy', () => {
    const exact = matchText('darslar', 'Darslar')!.score;
    const prefix = matchText('dars', 'Darslar')!.score;
    const word = matchText('mark', 'Situatsion markaz')!.score;
    const sub = matchText('arkaz', 'Situatsion markaz')!.score;
    const fuzzy = matchText('stmrk', 'Situatsion markaz')!.score;
    expect(exact).toBeGreaterThan(prefix);
    expect(prefix).toBeGreaterThan(word);
    expect(word).toBeGreaterThan(sub);
    expect(sub).toBeGreaterThan(fuzzy);
  });

  it('requires every token and matches across apostrophe variants', () => {
    expect(matchText("o'qit", 'O‘qituvchilar')!.ranges).toEqual([{ start: 0, end: 5 }]);
    expect(matchText('normal anat', 'Normal anatomiya kafedrasi')!.ranges).toEqual([
      { start: 0, end: 6 },
      { start: 7, end: 11 },
    ]);
    expect(matchText('xyz', 'Darslar')).toBeNull();
  });
});

describe('highlight', () => {
  it('splits text into matched parts', () => {
    expect(highlight('Darslar', [{ start: 0, end: 4 }])).toEqual([
      { text: 'Dars', match: true },
      { text: 'lar', match: false },
    ]);
    expect(highlight('abc', [])).toEqual([{ text: 'abc', match: false }]);
    expect(
      highlight('abcdef', [
        { start: 1, end: 2 },
        { start: 2, end: 4 },
      ]),
    ).toEqual([
      { text: 'a', match: false },
      { text: 'bcd', match: true },
      { text: 'ef', match: false },
    ]);
  });
});

describe('rankItems', () => {
  const items = [
    { id: '1', title: 'Hisobotlar' },
    { id: '2', title: 'Hodisalar' },
    { id: '3', title: 'Kameralar', keywords: ['video', 'cctv'] },
    { id: '4', title: 'Videodevor' },
  ];

  it('orders by score and keeps original order for an empty query', () => {
    expect(rankItems('hod', items).map((r) => r.item.id)).toEqual(['2']);
    expect(rankItems('', items).map((r) => r.item.id)).toEqual(['1', '2', '3', '4']);
  });

  it('scores keyword hits below title hits', () => {
    expect(rankItems('video', items).map((r) => r.item.id)).toEqual(['4', '3']);
  });

  it('respects the limit', () => {
    expect(rankItems('lar', items, 1)).toHaveLength(1);
  });
});

describe('recent items', () => {
  it('dedupes, limits and survives bad JSON', () => {
    const s = memoryStorage();
    pushRecent({ kind: 'page', id: '/', title: 'A', to: '/' }, s);
    pushRecent({ kind: 'page', id: '/x', title: 'B', to: '/x' }, s);
    const list = pushRecent({ kind: 'page', id: '/', title: 'A', to: '/' }, s);
    expect(list.map((r) => r.id)).toEqual(['/', '/x']);
    for (let i = 0; i < 12; i += 1) pushRecent({ kind: 'group', id: `g${i}`, title: `G${i}`, to: `/g${i}` }, s);
    expect(loadRecent(s)).toHaveLength(8);
    s.setItem(RECENT_KEY, '{oops');
    expect(loadRecent(s)).toEqual([]);
  });
});
