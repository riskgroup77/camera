"""deploy/monitoring/ — Prometheus qoidalari, Grafana dashboardi va
Alertmanager sozlamasi /metrics bilan mos ekanini tekshirish.

Serverda xato sozlama faqat `up.sh` dagi promtool/amtool'da ko'rinardi;
bu testlar uni CI'da, metrika nomi o'zgarganda darhol ushlaydi."""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MONITORING = ROOT / "deploy" / "monitoring"
METRICS_SOURCE = ROOT / "camera-api" / "app" / "routers" / "metrics.py"

pytestmark = pytest.mark.skipif(not MONITORING.exists(), reason="deploy/ katalogi yo'q (konteyner ichida)")


@pytest.fixture(scope="module")
def render():
    spec = importlib.util.spec_from_file_location("render_alertmanager", MONITORING / "render_alertmanager.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_alertmanager"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("render_alertmanager", None)


def _exported_metric_names() -> set[str]:
    source = METRICS_SOURCE.read_text(encoding="utf-8")
    names = {f"sm_{name}" for name in re.findall(r'_gauge\(\s*"([a-z_]+)"', source)}
    names.add("sm_app_info")
    return names


def _referenced_sm_metrics(text: str) -> set[str]:
    return set(re.findall(r"\bsm_[a-z_]+\b", text))


def _rules() -> list[dict]:
    data = yaml.safe_load((MONITORING / "prometheus" / "rules" / "camera.rules.yml").read_text(encoding="utf-8"))
    return [rule for group in data["groups"] for rule in group["rules"]]


class TestPrometheus:
    def test_config_parses_and_loads_rules(self):
        config = yaml.safe_load((MONITORING / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"))
        jobs = {job["job_name"]: job for job in config["scrape_configs"]}
        assert {"camera-api", "node", "cadvisor"} <= set(jobs)
        # API override'dagi port bilan bir xil (deploy/docker-compose.override.yml).
        override = (ROOT / "deploy" / "docker-compose.override.yml").read_text(encoding="utf-8")
        assert "127.0.0.1:18080:8080" in override
        assert jobs["camera-api"]["static_configs"][0]["targets"] == ["127.0.0.1:18080"]
        assert config["rule_files"] == ["/etc/prometheus/rules/*.yml"]

    def test_every_alert_is_labelled_and_described(self):
        rules = _rules()
        assert len(rules) >= 10
        names = [rule["alert"] for rule in rules]
        assert len(names) == len(set(names))
        for rule in rules:
            assert rule["labels"]["severity"] in {"warning", "critical"}, rule["alert"]
            assert rule["annotations"]["summary"], rule["alert"]
            assert rule["annotations"]["description"], rule["alert"]

    def test_rules_only_use_exported_metrics(self):
        text = (MONITORING / "prometheus" / "rules" / "camera.rules.yml").read_text(encoding="utf-8")
        assert _referenced_sm_metrics(text) <= _exported_metric_names()

    def test_required_alerts_exist(self):
        names = {rule["alert"] for rule in _rules()}
        for required in ("ApiIshlamayapti", "KameralarOflayn20Foizdan", "DiskToldi85Foiz", "XotiraYuqori",
                         "MuddatiOtganHodisalarKopaydi", "IshVaqtidaDavomatYozilmayapti"):
            assert required in names

    def test_alertmanager_inhibitions_name_real_alerts(self, render):
        names = {rule["alert"] for rule in _rules()}
        config = render.render({})
        for alternation in re.findall(r'alertname=~?\\?"([^"\\]+)', config):
            for name in alternation.split("|"):
                assert name in names, name


class TestGrafana:
    def test_dashboard_is_valid_and_uses_provisioned_datasource(self):
        dashboard = json.loads(
            (MONITORING / "grafana" / "dashboards" / "situatsion-markaz.json").read_text(encoding="utf-8")
        )
        datasource = yaml.safe_load(
            (MONITORING / "grafana" / "provisioning" / "datasources" / "prometheus.yml").read_text(encoding="utf-8")
        )["datasources"][0]
        assert dashboard["uid"] == "situatsion-markaz"
        ids = [panel["id"] for panel in dashboard["panels"]]
        assert len(ids) == len(set(ids))
        for panel in dashboard["panels"]:
            if panel["type"] == "row":
                continue
            assert panel["datasource"]["uid"] == datasource["uid"]
            assert panel["targets"], panel["title"]

    def test_dashboard_only_uses_exported_metrics(self):
        text = (MONITORING / "grafana" / "dashboards" / "situatsion-markaz.json").read_text(encoding="utf-8")
        referenced = _referenced_sm_metrics(text)
        assert {"sm_cameras_active", "sm_events_overdue", "sm_attendance_records_today"} <= referenced
        assert referenced <= _exported_metric_names()


class TestAlertmanagerRender:
    def test_without_telegram_nothing_is_sent(self, render):
        config = yaml.safe_load(render.render({}))
        assert config["receivers"] == [{"name": "telegram"}]
        assert config["route"]["receiver"] == "telegram"

    def test_telegram_receiver(self, render):
        token = "123456789:AAFakeTokenForTests_abcdefghijklmnop"
        config = yaml.safe_load(render.render({
            "TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": "-1001234567890", "TELEGRAM_MESSAGE_THREAD_ID": "7",
        }))
        telegram = config["receivers"][0]["telegram_configs"][0]
        assert telegram["bot_token"] == token
        assert telegram["chat_id"] == -1001234567890
        assert telegram["message_thread_id"] == 7
        assert telegram["send_resolved"] is True
        assert "sm.telegram.message" in telegram["message"]

    @pytest.mark.parametrize("values", [
        {"TELEGRAM_BOT_TOKEN": "123456789:AAFakeTokenForTests_abcdefghijklmnop"},
        {"TELEGRAM_CHAT_ID": "123"},
        {"TELEGRAM_BOT_TOKEN": "not-a-token", "TELEGRAM_CHAT_ID": "123"},
        {"TELEGRAM_BOT_TOKEN": "123456789:AAFakeTokenForTests_abcdefghijklmnop", "TELEGRAM_CHAT_ID": "@kanal"},
        {"ALERT_REPEAT_INTERVAL": "sometimes"},
    ])
    def test_invalid_values_are_rejected(self, render, values):
        with pytest.raises(ValueError):
            render.render(values)

    def test_env_parsing_strips_quotes_and_comments(self, render):
        values = render.parse_env('# izoh\nTELEGRAM_CHAT_ID="-100"\n\nGRAFANA_ADMIN_PASSWORD=a=b\n')
        assert values == {"TELEGRAM_CHAT_ID": "-100", "GRAFANA_ADMIN_PASSWORD": "a=b"}

    def test_main_writes_private_file(self, render, tmp_path):
        env = tmp_path / ".env"
        env.write_text("TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n", encoding="utf-8")
        out = tmp_path / "am" / "alertmanager.generated.yml"
        assert render.main(["x", str(env), str(out)]) == 0
        assert yaml.safe_load(out.read_text(encoding="utf-8"))["receivers"][0]["name"] == "telegram"


class TestPinnedImages:
    @pytest.mark.parametrize("compose", [
        ROOT / "camera-api" / "docker-compose.yml",
        MONITORING / "docker-compose.monitoring.yml",
    ])
    def test_no_floating_tags(self, compose):
        images = re.findall(r"^\s*image:\s*(\S+)", compose.read_text(encoding="utf-8"), flags=re.M)
        assert images
        for image in images:
            tag = image.rsplit("/", 1)[-1].partition(":")[2]
            assert tag and tag != "latest", image

    def test_mediamtx_versions_match(self):
        compose = (ROOT / "camera-api" / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "deploy" / "Dockerfile.mediamtx").read_text(encoding="utf-8")
        version = re.search(r"bluenviron/mediamtx:(\S+)", compose).group(1)
        assert f"bluenviron/mediamtx:{version} AS mtx" in dockerfile
