"""HEMIS rasm manzili (app/jobs/hemis_photos.py photo_candidates)."""

from app.jobs.hemis_photos import photo_candidates


def test_staff_photo_also_tries_the_path_without_uploads():
    # fjsti HEMIS (2026-10-06): xodim rasmi ".../static/uploads/pi/..." — 404,
    # rasm esa ".../static/pi/..." da (talabalarniki shu shaklda).
    url = "https://hemis.fjsti.uz/static/uploads/pi/a/b/photo.jpg"
    assert photo_candidates(url) == [url, "https://hemis.fjsti.uz/static/pi/a/b/photo.jpg"]


def test_student_photo_is_tried_as_is():
    url = "https://hemis.fjsti.uz/static/pi/a/b/photo.jpg"
    assert photo_candidates(url) == [url]
