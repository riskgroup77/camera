import { Page } from '../../ui';
import ScheduleBoard from '../../components/schedule/ScheduleBoard';

/**
 * Dars jadvali — HEMIS'dan har 3 soatda keladi (app/jobs/hemis_schedule.py).
 *
 * Har bir dars: o'qituvchini va guruh talabalarini kameralar bugun ko'rdimi,
 * xonada nechta odam bor. Qo'lda Excel yuklash olib tashlandi: HEMIS
 * jadvali bilan ikki nusxa (hemis_id siz qatorlar) paydo bo'lardi.
 */
export default function DarsJadvaliPage() {
  return (
    <Page title="Dars jadvali" subtitle="HEMIS jadvali bo'yicha: kim darsda, kim yo'q">
      <ScheduleBoard />
    </Page>
  );
}
