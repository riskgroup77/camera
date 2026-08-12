import { useRef, useState } from 'react';
import { AlertTriangle, FileText, Loader2, Upload } from 'lucide-react';
import { PdfRenderTimeoutError, renderPdfFirstPageToDataUrl } from '../../lib/pdf';
import { uploadFile } from '../../lib/fileUpload';
import { useAuth } from '../../lib/auth';

const MAX_SIZE_MB = 10;

interface PassportUploadStepProps {
  onLoaded: (previewDataUrl: string, fileName: string) => void;
}

export default function PassportUploadStep({ onLoaded }: PassportUploadStepProps) {
  const { token } = useAuth();
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
    try {
      // Asl PDF faylni "arxiv" xizmati orqali saqlaymiz (backend tayyor bo'lganda
      // shu joyda haqiqiy serverga yuklanadi) — vizual preview esa alohida,
      // yuzni solishtirish uchun kerakli piksel ma'lumotini beruvchi rasmga render qilinadi.
      await uploadFile(file, file.name, token, 'passports');
      const dataUrl = await renderPdfFirstPageToDataUrl(file);
      setPreview({ url: dataUrl, name: file.name });
      onLoaded(dataUrl, file.name);
    } catch (err) {
      setError(
        err instanceof PdfRenderTimeoutError
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
          <img
            src={preview.url}
            alt="Pasport sahifasi"
            className="max-h-64 rounded-xl border border-white/80 dark:border-white/10 object-contain shadow-btn"
          />
          <p className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
            <FileText size={13} />
            {preview.name}
          </p>
          <button type="button" onClick={() => inputRef.current?.click()} className="btn-glass text-xs">
            Boshqa fayl tanlash
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={loading}
          className="flex min-h-[180px] w-full max-w-sm flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-indigo-200 bg-indigo-50/50 dark:bg-indigo-500/10 text-sm font-semibold text-indigo-500 transition-colors hover:bg-indigo-50"
        >
          {loading ? (
            <>
              <Loader2 size={22} className="animate-spin" />
              PDF o'qilmoqda...
            </>
          ) : (
            <>
              <Upload size={22} />
              Pasport nusxasini yuklang (PDF)
              <span className="text-xs font-normal text-indigo-400">
                Bosing yoki faylni bu yerga tashlang
              </span>
            </>
          )}
        </button>
      )}

      {error && (
        <p className="flex items-center gap-1.5 text-xs font-medium text-red-500 dark:text-red-400">
          <AlertTriangle size={13} />
          {error}
        </p>
      )}
    </div>
  );
}
