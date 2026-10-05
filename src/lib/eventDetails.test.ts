import { describe, expect, it } from 'vitest';
import { detailMetrics, formatMetric } from './eventDetails';

describe('formatMetric', () => {
  it('formats fractions, decimals and integers the Uzbek way', () => {
    expect(formatMetric('fire_fraction', 0.0153)).toBe('1,5%');
    expect(formatMetric('closest', 0.4567)).toBe('0,46');
    expect(formatMetric('people', 3)).toBe('3');
    expect(formatMetric('closest', null)).toBe('—');
  });
});

describe('detailMetrics', () => {
  it('labels known keys, keeps unknown ones and drops empty values', () => {
    expect(
      detailMetrics({ reason: 'x', metrics: { unmatched: 2, closest: null, custom_value: 'a' } }),
    ).toEqual([
      { key: 'unmatched', label: 'Tanilmagan yuzlar', value: '2' },
      { key: 'custom_value', label: 'custom_value', value: 'a' },
    ]);
    expect(detailMetrics(null)).toEqual([]);
  });
});
