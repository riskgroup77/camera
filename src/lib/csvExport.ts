export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Ba'zi brauzerlar yuklab olishni boshlashga ulgurmasdan havola bekor
  // qilinsa faylni tashlab yuboradi — shuning uchun keyingi tsiklda tozalaymiz.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Excel ru/uz sozlamalarida ro'yxat ajratgichi — nuqta-vergul. Vergul bilan
 *  yozilgan fayl bitta ustunga yopishib qolardi. `sep=;` birinchi qatori
 *  Excel'ga ajratgichni aniq aytadi, boshqa dasturlar esa uni e'tiborsiz
 *  qoldiradi yoki nuqta-vergulni o'zi taniydi. */
const SEP = ';';

export function exportRowsAsCsv(headers: string[], rows: (string | number)[][], filename: string) {
  const allRows = [headers, ...rows];
  const csv = allRows
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(SEP))
    .join('\r\n');

  const blob = new Blob(['﻿' + `sep=${SEP}\r\n` + csv], { type: 'text/csv;charset=utf-8' });
  downloadBlob(blob, filename);
}
