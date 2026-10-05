import { useEffect, useRef, useState } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { Button, Field, Modal, Textarea } from '../../ui';

const MAX_NOTE = 2000;

/** "Hal qilindi" — qanday chora ko'rilgani majburiy yoziladi (bitta hodisa
 *  uchun ham, bir nechtasi uchun ham). Xato bo'lsa dialog ochiq qoladi. */
export default function ResolveDialog({
  open,
  count = 1,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  count?: number;
  onCancel: () => void;
  onConfirm: (note: string) => Promise<void>;
}) {
  const [note, setNote] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) {
      setNote('');
      setError(null);
      setPending(false);
    }
  }, [open]);

  const trimmed = note.trim();

  async function submit() {
    if (!trimmed || pending) return;
    setPending(true);
    setError(null);
    try {
      await onConfirm(trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Saqlab bo'lmadi");
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={pending ? () => undefined : onCancel}
      dismissible={!pending}
      title="Hal qilindi"
      description={count > 1 ? `${count} ta hodisa yopiladi.` : undefined}
      initialFocusRef={noteRef}
      footer={
        <>
          <Button onClick={onCancel} disabled={pending}>
            Bekor qilish
          </Button>
          <Button variant="primary" icon={CheckCircle2} onClick={submit} loading={pending} disabled={!trimmed}>
            Hal qilindi
          </Button>
        </>
      }
    >
      <Field label="Yechim izohi" required error={error} hint={`${note.length} / ${MAX_NOTE}`}>
        <Textarea
          ref={noteRef}
          value={note}
          onChange={(e) => setNote(e.target.value.slice(0, MAX_NOTE))}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={4}
          placeholder="Masalan: navbatchi yuborildi"
        />
      </Field>
    </Modal>
  );
}
