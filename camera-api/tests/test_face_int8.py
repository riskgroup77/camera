"""CPU'da INT8 model tanlash (app/services/face_recognition.py _int8_model_file)."""

from app.config import settings
from app.services import face_recognition as fr


def test_int8_file_is_created_once_and_used(tmp_path, monkeypatch):
    model = tmp_path / "w600k_r50.onnx"
    model.write_bytes(b"fp32")
    calls = []

    def fake_quantize(src, dst, weight_type=None):
        calls.append((src, dst))
        with open(dst, "wb") as fh:
            fh.write(b"int8")

    import onnxruntime.quantization as q

    monkeypatch.setattr(q, "quantize_dynamic", fake_quantize)
    monkeypatch.setattr(settings, "face_recognition_int8", True)
    path = fr._int8_model_file(str(model), "recognition")
    assert path.endswith("w600k_r50.int8.onnx") and open(path, "rb").read() == b"int8"
    assert fr._int8_model_file(str(model), "recognition") == path and len(calls) == 1  # keshdan


def test_disabled_or_other_models_keep_fp32(tmp_path, monkeypatch):
    model = tmp_path / "1k3d68.onnx"
    model.write_bytes(b"fp32")
    monkeypatch.setattr(settings, "face_recognition_int8", False)
    assert fr._int8_model_file(str(model), "recognition") == str(model)
    assert fr._int8_model_file(str(model), "landmark_3d_68") == str(model)


def test_quantization_failure_falls_back_to_fp32(tmp_path, monkeypatch):
    model = tmp_path / "det_10g.onnx"
    model.write_bytes(b"fp32")

    def broken(*args, **kwargs):
        raise RuntimeError("buzilgan model")

    import onnxruntime.quantization as q

    monkeypatch.setattr(q, "quantize_dynamic", broken)
    monkeypatch.setattr(settings, "face_detection_int8", True)
    assert fr._int8_model_file(str(model), "detection") == str(model)
