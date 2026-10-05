import { useRef, useState } from 'react';
import { AlertTriangle, FileText, Loader2, Upload } from 'lucide-react';
import { Button, cn, focusRing } from '../../ui';

const MAX_SIZE_MB = 10;

interface PassportUploadStepProps {
  onLoaded: (previewDataUrl: string, fileName: string) => void;
}

export default function PassportUploadStep({ onLoaded }: PassportUploadStepProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ url: string; name: string } | null>(null);

  async function handleFile(file: File) {
    setError(null);

    if (file.type !== 'application/pdf') {
      setError('Faqat PDF formatidagi fayl qabul qilinadi');
      return;
    }
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      setError(`Fayl hajmi ${MAX_SIZE_MB} MB dan oshmasligi kerak`);
      return;
    }

    setLoading(true);
    // pdf.js (~400 KB) faqat PDF tanlanganda yuklanadi — "Talabalar va
    // Xodimlar" sahifasi ochilishi uni kutib turmaydi.
    let pdf: typeof import('../../lib/pdf') | null = null;
    try {
      pdf = await import('../../lib/pdf');
      // Pasport faqat brauzerda — yuzni solishtirish uchun rasmga aylantiriladi.
      // Serverga yuklanmaydi: ilgari har bir PDF "passports/" ga tushib, hech
      // qaysi yozuvga bog'lanmagan shaxsiy hujjat bo'lib qolardi.
      const dataUrl = await pdf.renderPdfFirstPageToDataUrl(file);
      setPreview({ url: dataUrl, name: file.name });
      onLoaded(dataUrl, file.name);
    } catch (err) {
      setError(
        pdf === null
          ? "PDF o'quvchini yuklab bo'lmadi — sahifani yangilang va qayta urinib ko'ring"
          : err instanceof pdf.PdfRenderTimeoutError
            ? "PDF sahifasini render qilish juda uzoq davom etmoqda. Brauzeringiz Web Worker'larni cheklagan bo'lishi mumkin — boshqa brauzerda urinib ko'ring yoki qayta yuklang"
            : "PDF faylni o'qib bo'lmadi, boshqa fayl tanlang",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-4">
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
        }}
      />

      {preview ? (
        <div className="flex flex-col items-center gap-3">
          <img src={preview.url} alt="Pasport sahifasi" className="max-h-64 rounded-card border border-border object-contain shadow-card" />
          <p className="flex items-center gap-1.5 text-xs text-muted">
            <FileText size={13} aria-hidden="true" />
            {preview.name}
          </p>
          <Button size="sm" onClick={() => inputRef.current?.click()}>
            Boshqa fayl tanlash
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files?.[0];
            if (file && !loading) handleFile(file);
          }}
          disabled={loading}
          className={cn(
            'flex min-h-[180px] w-full max-w-sm flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-primary/30 bg-primary-soft/50 text-sm font-semibold text-primary transition-colors hover:bg-primary-soft disabled:cursor-wait',
            focusRing,
          )}
        >
          {loading ? (
            <>
              <Loader2 size={22} className="animate-spin" aria-hidden="true" />
              PDF o'qilmoqda...
            </>
          ) : (
            <>
              <Upload size={22} aria-hidden="true" />
              Pasport nusxasini yuklang (PDF)
              <span className="text-xs font-normal text-muted">Bosing yoki faylni bu yerga tashlang</span>
            </>
          )}
        </button>
      )}

      {error && (
        <p role="alert" className="flex items-center gap-1.5 text-xs font-medium text-danger">
          <AlertTriangle size={13} className="shrink-0" aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
}
