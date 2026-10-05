import { useState } from 'react';
import { FileDown } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import { Button, useToast } from '../../ui';

/** "PDF" tugmasi — ekrandagi filtr natijasini PDF qilib yuklab oladi. */
export default function PdfButton({
  path,
  params,
  filename,
  label = 'PDF',
}: {
  path: string;
  params: Record<string, string | number | undefined | null>;
  filename: string;
  label?: string;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      // Kechiktirilgan import: tugma chizilishi uchun yuklab olish kodi kerak emas.
      // Token apiClient ning o'zidan olinadi (joriy sessiya).
      const { downloadPdf } = await import('../../lib/pdfDownload');
      await downloadPdf(path, params, filename);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'PDF ni yuklab bo‘lmadi');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button size="sm" icon={FileDown} onClick={run} disabled={busy} title="Filtr natijasini PDF qilib yuklab olish">
      {busy ? 'Tayyorlanmoqda…' : label}
    </Button>
  );
}
