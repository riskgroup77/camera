import { useEffect, useState } from 'react';
import { Loader2, Trophy } from 'lucide-react';
import Modal from './Modal';
import { api } from '../lib/apiClient';
import type { TopStudent } from '../types';

const MEDAL = ['🥇', '🥈', '🥉'];

export default function TopStudentsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [students, setStudents] = useState<TopStudent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get<TopStudent[]>('/api/public/top-students')
      .then((res) => {
        setStudents(res);
        setError(null);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [open]);

  return (
    <Modal open={open} onClose={onClose} title="Namunali talabalar" maxWidth="max-w-md">
      <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        Ushbu oy davomida eng yuqori davomat ko'rsatkichiga ega talabalar reytingi
      </p>
      {loading ? (
        <div className="flex items-center justify-center py-8 text-slate-400">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : error ? (
        <p className="rounded-xl bg-red-50 px-3 py-2.5 text-xs font-semibold text-red-600 dark:bg-red-500/10 dark:text-red-400">
          {error}
        </p>
      ) : students.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400 dark:border-white/10 dark:text-slate-500">
          Bu oy uchun hali davomat yozuvlari yo'q
        </p>
      ) : (
        <ol className="space-y-2">
          {students.map((s, i) => (
            <li
              key={s.id}
              className="glass-deep flex items-center gap-3 px-4 py-3"
            >
              <span className="w-7 text-center text-lg">
                {MEDAL[i] ?? (
                  <span className="text-sm font-bold text-slate-400 dark:text-slate-500">{i + 1}</span>
                )}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-bold text-slate-900 dark:text-slate-100">{s.name}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400">{s.group}</p>
              </div>
              <span className="flex items-center gap-1 text-sm font-extrabold text-emerald-600 dark:text-emerald-400">
                <Trophy size={13} />
                {s.attendanceRate}%
              </span>
            </li>
          ))}
        </ol>
      )}
    </Modal>
  );
}
