import * as pdfjsLib from 'pdfjs-dist';
import pdfWorkerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerSrc;

const RENDER_TIMEOUT_MS = 20000;

export class PdfRenderTimeoutError extends Error {
  constructor() {
    super('PDF sahifasini render qilish vaqti tugadi');
    this.name = 'PdfRenderTimeoutError';
  }
}

export async function renderPdfFirstPageToDataUrl(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: buffer }).promise;
  const page = await pdf.getPage(1);

  const viewport = page.getViewport({ scale: 2 });
  const canvas = document.createElement('canvas');
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas 2D konteksti mavjud emas');

  const renderTask = page.render({ canvas, canvasContext: ctx, viewport });

  let timedOut = false;
  let timeoutId: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(() => {
      timedOut = true;
      reject(new PdfRenderTimeoutError());
      renderTask.cancel();
    }, RENDER_TIMEOUT_MS);
  });

  try {
    await Promise.race([renderTask.promise, timeout]);
  } catch (err) {
    throw timedOut ? new PdfRenderTimeoutError() : err;
  } finally {
    clearTimeout(timeoutId!);
  }

  return canvas.toDataURL('image/png');
}
