"""Hisobotning "Qisqa xulosa" qoidalari — har biri chegaradan oldin va keyin."""

from dataclasses import replace

from app.services.report_insights import MAX_INSIGHTS, InsightInputs, build_insights


def healthy(**overrides) -> InsightInputs:
    base = InsightInputs(
        staff_rate=90.0,
        staff_previous_rate=91.0,
        staff_previous_records=500,
        staff_reliable=True,
        staff_records=500,
        staff_present=450,
        staff_late_share=5.0,
        stale_serious_unreviewed=0,
        oldest_unreviewed_hours=None,
        total_events=100,
        night_events=2,
        top_camera_name="Kirish-1",
        top_camera_share=20.0,
        weak_modules=[],
        cameras_active=100,
        cameras_live_rate=98.0,
        students_coverage=80.0,
        students_population=6000,
    )
    return replace(base, **overrides)


def titles(inputs: InsightInputs) -> list[str]:
    return [insight.title for insight in build_insights(inputs)]


class TestHealthyPeriod:
    def test_no_problem_gives_a_single_ok_card(self):
        insights = build_insights(healthy())
        assert len(insights) == 1
        assert insights[0].level == "ok"


class TestAttendance:
    def test_drop_of_five_points_is_a_warning(self):
        insights = build_insights(healthy(staff_rate=86.0, staff_previous_rate=91.0))
        assert insights[0].level == "warning"
        assert insights[0].title == "Xodimlar davomati pasaydi"
        assert "91% dan 86% ga" in insights[0].text

    def test_drop_under_five_points_is_ignored(self):
        assert "Xodimlar davomati pasaydi" not in titles(healthy(staff_rate=86.5, staff_previous_rate=91.0))

    def test_small_or_unreliable_sample_never_claims_a_trend(self):
        assert "Xodimlar davomati pasaydi" not in titles(healthy(staff_rate=60.0, staff_reliable=False))
        assert "Xodimlar davomati pasaydi" not in titles(healthy(staff_rate=60.0, staff_previous_records=10))

    def test_records_without_any_presence_means_recognition_is_broken(self):
        insights = build_insights(healthy(staff_present=0, staff_rate=0.0, staff_reliable=False))
        assert insights[0].level == "critical"
        assert insights[0].title == "Kameralar birorta xodimni tanimagan"
        assert insights[0].action_href == "/oqituvchilar"

    def test_late_share_threshold(self):
        assert "Kech qolish ko'p" in titles(healthy(staff_late_share=15.0))
        assert "Kech qolish ko'p" not in titles(healthy(staff_late_share=14.9))


class TestSecurity:
    def test_stale_serious_signals_are_critical_and_first(self):
        insights = build_insights(
            healthy(stale_serious_unreviewed=3, oldest_unreviewed_hours=50.0, staff_late_share=30.0)
        )
        assert insights[0].level == "critical"
        assert insights[0].title == "Jiddiy signallar ko'rib chiqilmagan"
        assert "50 soat" in insights[0].text

    def test_one_camera_dominating_needs_enough_events(self):
        assert "Signallarning ko'pi bitta kameradan" in titles(healthy(top_camera_share=40.0, total_events=20))
        assert "Signallarning ko'pi bitta kameradan" not in titles(healthy(top_camera_share=90.0, total_events=19))
        assert "Signallarning ko'pi bitta kameradan" not in titles(healthy(top_camera_share=39.9))

    def test_weak_modules_are_listed_worst_first_and_capped(self):
        insights = build_insights(
            healthy(weak_modules=[("Chekish", 40.0, 20), ("Jang", 10.0, 30), ("Niqob", 30.0, 12)])
        )
        weak = [i for i in insights if i.title == "Modul ko'p yolg'on signal bermoqda"]
        assert len(weak) == 2
        assert "«Jang»" in weak[0].text and "«Niqob»" in weak[1].text

    def test_night_share(self):
        assert "Ish vaqtidan tashqari signallar" in titles(healthy(total_events=50, night_events=5))
        assert "Ish vaqtidan tashqari signallar" not in titles(healthy(total_events=50, night_events=4))
        assert "Ish vaqtidan tashqari signallar" not in titles(healthy(total_events=4, night_events=4))


class TestSystem:
    def test_camera_outage_levels(self):
        assert build_insights(healthy(cameras_live_rate=69.0))[0].level == "critical"
        warning = [i for i in build_insights(healthy(cameras_live_rate=85.0)) if i.title.startswith("Kameralarning")]
        assert warning and warning[0].level == "warning"
        assert "Kameralarning bir qismi ishlamayapti" not in titles(healthy(cameras_live_rate=90.0))

    def test_low_student_coverage_is_explained(self):
        insights = build_insights(healthy(students_coverage=0.0))
        assert insights[0].level == "info"
        assert "atigi 0%" in insights[0].text


def test_never_more_than_the_maximum():
    inputs = healthy(
        staff_present=0,
        staff_late_share=40.0,
        stale_serious_unreviewed=5,
        top_camera_share=80.0,
        weak_modules=[("A", 10.0, 20), ("B", 20.0, 20)],
        cameras_live_rate=50.0,
        students_coverage=1.0,
        night_events=50,
    )
    insights = build_insights(inputs)
    assert len(insights) == MAX_INSIGHTS
    levels = [i.level for i in insights]
    assert levels == sorted(levels, key=["critical", "warning", "info", "ok"].index)
