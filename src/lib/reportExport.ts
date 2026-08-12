import { jsPDF } from 'jspdf';
import type { Report } from '../types';

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

function wrapText(doc: jsPDF, text: string, maxWidth: number): string[] {
  return doc.splitTextToSize(text, maxWidth);
}

export function exportReportAsPdf(report: Report) {
  const doc = new jsPDF({ unit: 'pt', format: 'a4' });
  const marginX = 48;
  const pageWidth = doc.internal.pageSize.getWidth();
  const contentWidth = pageWidth - marginX * 2;
  let y = 64;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(16);
  doc.text("Farg'ona JSSTI — Situatsion Markaz hisoboti", marginX, y);
  y += 22;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(11);
  doc.setTextColor(90);
  doc.text(`${report.period} hisobot — ${report.periodLabel}`, marginX, y);
  y += 16;
  doc.text(`Generatsiya vaqti: ${report.generatedAt}`, marginX, y);
  y += 16;
  doc.text(`Manba: ${report.source === 'llm' ? "Claude API (LLM)" : 'Qoida-asosida (rule-based)'}`, marginX, y);
  y += 28;

  doc.setDrawColor(220);
  doc.line(marginX, y, pageWidth - marginX, y);
  y += 24;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.setTextColor(20);
  doc.text('Asosiy ko\'rsatkichlar', marginX, y);
  y += 18;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10.5);
  for (const stat of report.stats) {
    doc.setTextColor(90);
    doc.text(`${stat.label}:`, marginX, y);
    doc.setTextColor(20);
    doc.text(stat.value, marginX + 140, y);
    y += 16;
  }
  y += 16;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.setTextColor(20);
  doc.text("To'liq matn", marginX, y);
  y += 18;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10.5);
  doc.setTextColor(40);
  const lines = wrapText(doc, report.body, contentWidth);
  for (const line of lines) {
    if (y > doc.internal.pageSize.getHeight() - 48) {
      doc.addPage();
      y = 64;
    }
    doc.text(line, marginX, y);
    y += 15;
  }

  doc.save(`hisobot-${report.periodLabel.replace(/\s+/g, '_')}.pdf`);
}

export function exportReportAsCsv(report: Report) {
  const rows = [
    ['Davr', report.period],
    ['Sana/Oraliq', report.periodLabel],
    ['Generatsiya vaqti', report.generatedAt],
    ['Manba', report.source === 'llm' ? 'LLM' : 'Rule-based'],
    [],
    ['Ko\'rsatkich', 'Qiymat'],
    ...report.stats.map((s) => [s.label, s.value]),
    [],
    ['Xulosa', report.summary],
  ];

  const csv = rows
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\r\n');

  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
  downloadBlob(blob, `hisobot-${report.periodLabel.replace(/\s+/g, '_')}.csv`);
}
