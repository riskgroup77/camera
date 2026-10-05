import { useMemo, type CSSProperties } from 'react';
import { useTheme } from './themeContext';

/** Recharts uchun yagona uslub — ranglar CSS tokenlaridan (src/index.css)
 *  o'qiladi, shuning uchun qorong'i mavzu va taqdimot rejimida grafiklar
 *  ham o'zi moslashadi. Ma'no barcha sahifalarda bir xil:
 *  keldi = success, kech = warning, kelmadi = danger, ma'lumot yo'q = neutral. */
export interface ChartTheme {
  text: string;
  muted: string;
  axis: string;
  grid: string;
  surface: string;
  border: string;
  primary: string;
  success: string;
  warning: string;
  danger: string;
  info: string;
  neutral: string;
  /** Kategoriyalar uchun ketma-ket ranglar (fakultetlar, kurslar...). */
  series: string[];
  attendance: { keldi: string; kechKeldi: string; kelmadi: string; nomalum: string };
  severity: { past: string; orta: string; yuqori: string };
  /** <XAxis tick={theme.axisTick} /> */
  axisTick: { fill: string; fontSize: number };
  /** <Tooltip {...theme.tooltip} /> */
  tooltip: {
    contentStyle: CSSProperties;
    labelStyle: CSSProperties;
    itemStyle: CSSProperties;
    cursor: { fill: string };
  };
}

// jsdom va eski brauzerlar uchun zaxira (yorug' mavzu qiymatlari).
const FALLBACK: Record<string, string> = {
  fg: '17 24 39',
  muted: '99 107 121',
  subtle: '148 155 168',
  border: '226 229 235',
  surface: '255 255 255',
  'surface-2': '243 244 247',
  primary: '37 99 235',
  success: '21 128 61',
  warning: '180 83 9',
  danger: '220 38 38',
  info: '14 116 144',
  'chart-1': '37 99 235',
  'chart-2': '13 148 136',
  'chart-3': '124 58 237',
  'chart-4': '217 119 6',
  'chart-5': '219 39 119',
  'chart-6': '100 116 139',
};

/** Tokenni "rgb(r g b / a)" ko'rinishida o'qish. */
export function readToken(name: string, alpha = 1, element?: Element | null): string {
  let raw = '';
  if (typeof window !== 'undefined' && typeof getComputedStyle === 'function') {
    const target = element ?? document.documentElement;
    raw = getComputedStyle(target).getPropertyValue(`--c-${name}`).trim();
  }
  const channels = raw || FALLBACK[name] || '0 0 0';
  return alpha >= 1 ? `rgb(${channels})` : `rgb(${channels} / ${alpha})`;
}

/** Joriy CSS tokenlaridan tema yig'ish. `element` — mavzu shu element
 *  ichida boshqacha bo'lsa (masalan uslub qo'llanmasidagi qorong'i panel). */
export function readChartTheme(element?: Element | null): ChartTheme {
  const t = (name: string, alpha?: number) => readToken(name, alpha, element);
  const text = t('fg');
  const muted = t('muted');
  const surface = t('surface');
  const border = t('border');
  return {
    text,
    muted,
    axis: t('subtle'),
    grid: t('border', 0.8),
    surface,
    border,
    primary: t('primary'),
    success: t('success'),
    warning: t('warning'),
    danger: t('danger'),
    info: t('info'),
    neutral: t('subtle'),
    series: ['chart-1', 'chart-2', 'chart-3', 'chart-4', 'chart-5', 'chart-6'].map((name) => t(name)),
    attendance: { keldi: t('success'), kechKeldi: t('warning'), kelmadi: t('danger'), nomalum: t('subtle') },
    severity: { past: t('subtle'), orta: t('warning'), yuqori: t('danger') },
    axisTick: { fill: muted, fontSize: 11 },
    tooltip: {
      contentStyle: {
        background: surface,
        border: `1px solid ${border}`,
        borderRadius: 10,
        boxShadow: '0 12px 32px -8px rgb(16 24 40 / 0.25)',
        fontSize: 12,
        color: text,
        padding: '8px 10px',
      },
      labelStyle: { color: text, fontWeight: 600, marginBottom: 4 },
      itemStyle: { color: text, padding: 0 },
      cursor: { fill: t('surface-2', 0.8) },
    },
  };
}

/** Grafik komponentlari uchun: mavzu almashsa qayta hisoblanadi. */
export function useChartTheme(): ChartTheme {
  const { theme } = useTheme();
  // `theme` — faqat qayta o'qish signali: ranglar CSS'dan olinadi.
  return useMemo(() => {
    void theme;
    return readChartTheme();
  }, [theme]);
}
