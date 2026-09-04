import { jsPDF } from 'jspdf';
import type { Report, ReportSection } from '../types';

/**
 * Hisobotni PDF/CSV qilib chiqarish.
 *
 * Avvalgi versiyada uchta joylashuv nuqsoni bor edi va ular hisobot
 * o'sishi bilan darhol ko'rindi:
 *
 *  - qiymat ustuni QAT'IY 140pt da chizilardi, shuning uchun uzun
 *    yorliq ("Rad etilgan (yolg'on ijobiy)") qiymat ustiga chiqib
 *    ketardi;
 *  - sahifa oxiri faqat asosiy matnda tekshirilardi, ko'rsatkichlar
 *    ro'yxatida emas — bir necha qator qo'shilishi bilan matn sahifa
 *    tashqarisiga tushib, umuman ko'rinmay qolardi;
 *  - jadvallar (modul/kamera bo'yicha taqsimot) umuman chizilmasdi.
 *
 * Shrift ataylab jsPDF ning ichki helvetica'si bo'lib qoladi: hisobot
 * matnidagi yagona ASCII'dan tashqari belgi — uzun tire (—), u esa
 * WinAnsi'da bor. Tashqi shrift ulash faylni ~300 KB kattalashtiradi va
 * hech qanday muammoni hal qilmaydi.
 */

const MARGIN = 48;
const LINE = 15;
const BOTTOM_GUARD = 56;

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Sahifa oxiriga yetganda yangi sahifa ochadi va yangi `y` qaytaradi.
 *  Har bir chizishdan OLDIN chaqiriladi — avvalgi versiyaning asosiy
 *  nuqsoni aynan shu tekshiruvning faqat bitta joyda bo'lgani edi. */
function ensureSpace(doc: jsPDF, y: number, needed = LINE): number {
  if (y + needed > doc.internal.pageSize.getHeight() - BOTTOM_GUARD) {
    doc.addPage();
    return 64;
  }
  return y;
}

function drawRows(
  doc: jsPDF,
  rows: { label: string; value: string }[],
  y: number,
  contentWidth: number,
): number {
  const valueX = MARGIN + contentWidth;
  // Yorliq uchun joy = butun kenglik minus qiymat kengligi va oraliq.
  // Shu tarzda qiymat har doim o'ng chekkaga tekislanadi va ustma-ust
  // tushish mumkin emas, yorliq qanchalik uzun bo'lmasin.
  for (const row of rows) {
    y = ensureSpace(doc, y);
    const valueWidth = doc.getTextWidth(row.value);
    const labelWidth = contentWidth - valueWidth - 12;
    const [firstLine] = doc.splitTextToSize(row.label, Math.max(labelWidth, 40));
    doc.setTextColor(90);
    doc.text(firstLine, MARGIN, y);
    doc.setTextColor(20);
    doc.text(row.value, valueX, y, { align: 'right' });
    y += LINE;
  }
  return y;
}

function drawSection(doc: jsPDF, section: ReportSection, y: number, contentWidth: number): number {
  // Sarlavha yolg'iz qolib, jadvali keyingi sahifaga o'tib ketmasligi
  // uchun sarlavha + kamida ikki qator uchun joy talab qilinadi.
  y = ensureSpace(doc, y, LINE * 3);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(11);
  doc.setTextColor(20);
  doc.text(section.title, MARGIN, y);
  y += 16;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10);
  y = drawRows(doc, section.rows, y, contentWidth);

  if (section.note) {
    y += 4;
    doc.setFontSize(8.5);
    doc.setTextColor(120);
    for (const line of doc.splitTextToSize(section.note, contentWidth)) {
      y = ensureSpace(doc, y, 11);
      doc.text(line, MARGIN, y);
      y += 11;
    }
    doc.setFontSize(10);
  }
  return y + 14;
}

export function exportReportAsPdf(report: Report) {
  const doc = new jsPDF({ unit: 'pt', format: 'a4' });
  const pageWidth = doc.internal.pageSize.getWidth();
  const contentWidth = pageWidth - MARGIN * 2;
  let y = 64;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(16);
  doc.setTextColor(20);
  doc.text("Farg'ona JSSTI — Situatsion Markaz hisoboti", MARGIN, y);
  y += 22;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(11);
  doc.setTextColor(90);
  doc.text(`${report.period} hisobot — ${report.periodLabel}`, MARGIN, y);
  y += 16;
  doc.text(`Generatsiya vaqti: ${report.generatedAt}`, MARGIN, y);
  y += 28;

  doc.setDrawColor(220);
  doc.line(MARGIN, y, pageWidth - MARGIN, y);
  y += 24;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.setTextColor(20);
  doc.text("Asosiy ko'rsatkichlar", MARGIN, y);
  y += 18;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10.5);
  y = drawRows(doc, report.stats, y, contentWidth);
  y += 18;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.setTextColor(20);
  y = ensureSpace(doc, y, LINE * 3);
  doc.text('Xulosa', MARGIN, y);
  y += 18;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10.5);
  doc.setTextColor(40);
  for (const line of doc.splitTextToSize(report.body, contentWidth)) {
    y = ensureSpace(doc, y);
    doc.text(line, MARGIN, y);
    y += LINE;
  }
  y += 20;

  for (const section of report.sections ?? []) {
    y = drawSection(doc, section, y, contentWidth);
  }

  // Sahifa raqamlari oxirida qo'yiladi — bu paytda umumiy son ma'lum,
  // shuning uchun "3 / 5" ko'rinishida yozish mumkin.
  const pages = doc.getNumberOfPages();
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8.5);
    doc.setTextColor(150);
    doc.text(
      `${i} / ${pages}`,
      pageWidth - MARGIN,
      doc.internal.pageSize.getHeight() - 28,
      { align: 'right' },
    );
  }

  doc.save(`hisobot-${report.periodLabel.replace(/\s+/g, '_')}.pdf`);
}

export function exportReportAsCsv(report: Report) {
  const rows: string[][] = [
    ['Davr', report.period],
    ['Sana/Oraliq', report.periodLabel],
    ['Generatsiya vaqti', report.generatedAt],
    [],
    ["Ko'rsatkich", 'Qiymat'],
    ...report.stats.map((s) => [s.label, s.value]),
  ];

  for (const section of report.sections ?? []) {
    rows.push([], [section.title], ...section.rows.map((r) => [r.label, r.value]));
    if (section.note) rows.push(['Izoh', section.note]);
  }

  rows.push([], ['Xulosa', report.summary]);

  const csv = rows
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\r\n');

  // BOM — Excel CSV'ni UTF-8 deb tanishi uchun; bu bo'lmasa o'zbekcha
  // matn buzilib ochiladi.
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
  downloadBlob(blob, `hisobot-${report.periodLabel.replace(/\s+/g, '_')}.csv`);
}
