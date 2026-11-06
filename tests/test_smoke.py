"""Smoke tests for the Stage 0 skeleton: config loading and (optional) GPU visibility."""

import pytest

from studio import __version__
from studio.config import ConfigError, load_config


def test_version_is_set():
    assert __version__


def test_default_config_loads_and_has_expected_sections():
    config = load_config()
    assert {"app", "images", "hardware", "training"} <= set(config)
    assert config["app"]["host"] == "127.0.0.1"  # local-only default (Rule 1)


def test_missing_config_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(bad)


def test_non_mapping_config_raises(tmp_path):
    bad = tmp_path / "list.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(bad)


@pytest.mark.gpu
def test_cuda_is_visible_when_present():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("no CUDA GPU on this machine")
    assert torch.cuda.get_device_name(0)
