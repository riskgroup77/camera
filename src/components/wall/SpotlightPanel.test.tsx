import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SpotlightPanel } from './SpotlightPanel';

/** Bo'sh ekran ikki xil bo'ladi: ko'rsatadigan narsa yo'q, yoki
 *  tafsilot hali kelmadi. Ikkalasini bir xil yozish rahbarga
 *  "bugun hech kim yo'q" degan noto'g'ri xabar berardi. */
describe('SpotlightPanel — bo\'sh holat', () => {
  it("navbat bo'sh bo'lsa — ko'rsatiladigan narsa yo'qligi aytiladi", () => {
    render(<SpotlightPanel detail={null} index={0} total={0} rotateS={15} cycleKey={0} />);
    expect(screen.getByText("Bo'linma yo'q")).toBeInTheDocument();
  });

  it("navbat bor, lekin tafsilot kelmagan — 'yuklanmoqda' deyiladi", () => {
    render(<SpotlightPanel detail={null} index={0} total={4} rotateS={15} cycleKey={0} />);
    expect(screen.getByText(/yuklanmoqda/i)).toBeInTheDocument();
    expect(screen.queryByText("Bo'linma yo'q")).toBeNull();
  });
});
