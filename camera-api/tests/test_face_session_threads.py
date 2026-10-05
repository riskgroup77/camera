"""InsightFace ONNX sessiyalari cheklangan oqimlar bilan ishlaydi.

Productionda o'lchandi: 24 ta parallel yuz tanish chaqiruvi, har biri
onnxruntime standarti bo'yicha hostdagi barcha 32 yadroni ishlatib, 20
yadroli konteyner chegarasida yuklamani 110 ga chiqargan. insightface 1.0.1
sess_options'ni modellarga uzatmaydi, shuning uchun sessiyalar yuklangandan
keyin qayta yaratiladi."""

import pytest

from app.config import settings
from app.services import face_recognition


@pytest.fixture
def fresh_app(monkeypatch):
    # Global modelni shu test uchun qayta yuklaymiz; monkeypatch keyin asl
    # nusxani qaytaradi, boshqa testlar ta'sirlanmaydi.
    monkeypatch.setattr(face_recognition, "_app", None)
    return monkeypatch


class TestOnnxThreadLimit:
    def test_every_model_session_uses_configured_threads(self, fresh_app):
        fresh_app.setattr(settings, "face_recognition_intra_op_threads", 2)
        app = face_recognition._get_app()
        assert "detection" in app.models and "recognition" in app.models
        for name, model in app.models.items():
            options = model.session.get_session_options()
            assert options.intra_op_num_threads == 2, name
            assert options.inter_op_num_threads == 1, name

    def test_only_models_the_system_reads_are_loaded(self, fresh_app):
        app = face_recognition._get_app()
        assert set(app.models) == {"detection", "recognition", "landmark_3d_68"}
        # Hech qayerda o'qilmaydi, lekin har yuz uchun CPU yerdi.
        assert "genderage" not in app.models
        assert "landmark_2d_106" not in app.models

    def test_zero_keeps_onnxruntime_default(self, fresh_app):
        fresh_app.setattr(settings, "face_recognition_intra_op_threads", 0)
        app = face_recognition._get_app()
        # insightface o'zi yaratgan sessiya: oqim soni belgilanmagan (0 = standart).
        assert app.models["detection"].session.get_session_options().intra_op_num_threads == 0
