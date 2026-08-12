import { useEffect, useMemo, useState } from 'react';

export function usePagination<T>(items: T[], pageSize: number) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));

  // Filtrlar o'zgarib ro'yxat qisqarganda joriy sahifa mavjud bo'lmay qolsa, oxirgi sahifaga qaytariladi.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const pageItems = useMemo(() => {
    const start = (page - 1) * pageSize;
    return items.slice(start, start + pageSize);
  }, [items, page, pageSize]);

  return {
    page,
    setPage,
    totalPages,
    pageItems,
    total: items.length,
  };
}
