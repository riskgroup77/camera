"""scripts/camera_stream_settings.py — ISAPI XML ni maqsadli qiymatlarga keltirish."""

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "camera_stream_settings.py"

SUB_STREAM = """<?xml version="1.0" encoding="UTF-8"?>
<StreamingChannel version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <id>102</id>
  <Video>
    <videoCodecType>H.265</videoCodecType>
    <videoResolutionWidth>640</videoResolutionWidth>
    <videoResolutionHeight>360</videoResolutionHeight>
    <maxFrameRate>2500</maxFrameRate>
    <GovLength>100</GovLength>
    <SmartCodec><enabled>true</enabled></SmartCodec>
  </Video>
</StreamingChannel>"""


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("camera_stream_settings", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["camera_stream_settings"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("camera_stream_settings", None)


def test_reads_the_current_state(script):
    state = script.read_state(ET.fromstring(SUB_STREAM))
    assert (state.codec, state.fps, state.gov, state.smart) == ("H.265", 25.0, 100, "true")


def test_plan_sets_one_keyframe_per_second_h264_and_no_smart_codec(script):
    root = ET.fromstring(SUB_STREAM)
    plan = script.plan_changes(root, want_h264=True)
    assert len(plan.changes) == 3
    after = script.read_state(root)
    assert (after.codec, after.gov, after.smart) == ("H.264", 25, "false")
    # Qayta rejalashtirish — hech narsa o'zgarmaydi.
    assert script.plan_changes(root, want_h264=True).changes == []


def test_main_stream_keeps_its_codec(script):
    root = ET.fromstring(SUB_STREAM.replace("<SmartCodec><enabled>true</enabled></SmartCodec>", ""))
    plan = script.plan_changes(root, want_h264=False)
    assert plan.changes == ["GOP 100 -> 25 (har soniyada kalit kadr)"]
    assert script.read_state(root).codec == "H.265"


def test_xml_goes_back_without_namespace_prefixes(script):
    """2026-09-18: `<ns0:GovLength>` ga kameralar "OK" deb javob berib,
    hech narsani qo'llamagan — XML asl, prefikssiz ko'rinishda qaytishi shart."""
    root = ET.fromstring(SUB_STREAM)
    script.plan_changes(root, want_h264=True)
    body = script.to_xml(root).decode()
    assert "ns0:" not in body
    assert 'xmlns="http://www.hikvision.com/ver20/XMLSchema"' in body
    assert "<GovLength>25</GovLength>" in body


def test_read_back_detects_a_silently_ignored_write(script):
    wanted_xml = SUB_STREAM.replace("H.265", "H.264").replace(">100<", ">25<").replace(">true<", ">false<")
    wanted = script.read_state(ET.fromstring(wanted_xml))
    unchanged = script.read_state(ET.fromstring(SUB_STREAM))
    assert script.not_applied(wanted, unchanged) == ["kodek H.265", "GOP 100", "Smart Codec hali yoqiq"]
    assert script.not_applied(wanted, wanted) == []


def test_faqat_sub_touches_only_the_substream(script):
    import argparse

    assert script.channels_for(argparse.Namespace(faqat_sub=True)) == {"sub": "102"}
    assert script.channels_for(argparse.Namespace(faqat_sub=False)) == {"asosiy": "101", "sub": "102"}


CAPS_720 = '<Video><videoResolutionWidth opt="640,640,1280"/><videoResolutionHeight opt="360,480,720"/></Video>'
CAPS_768 = '<Video><videoResolutionWidth opt="640,768"/><videoResolutionHeight opt="360,432"/></Video>'


def test_substream_is_raised_to_720p_when_the_camera_supports_it(script):
    root = ET.fromstring(SUB_STREAM.replace("</Video>", "<vbrUpperCap>512</vbrUpperCap></Video>"))
    changes = script.plan_resolution(root, CAPS_720, 1280, 720, 1536)
    state = script.read_state(root)
    assert (state.width, state.height) == ("1280", "720")
    assert any("vbrUpperCap 512 -> 1536" in c for c in changes)


def test_unsupported_resolution_is_left_alone(script):
    root = ET.fromstring(SUB_STREAM)
    changes = script.plan_resolution(root, CAPS_768, 1280, 720, 1536)
    assert changes[0].startswith("!")
    assert script.read_state(root).width == "640"
