from pathlib import Path

import pytest
import yaml

from linkedin_apply.config import ConfigError, load_config, parse_config

ROOT = Path(__file__).resolve().parent.parent


def test_example_config_loads():
    cfg = load_config(ROOT / "config.example.yaml")
    assert cfg.behavior.dry_run is True
    assert cfg.limits.delay_seconds == (2.0, 6.0)
    assert cfg.answers and cfg.search.keywords


def test_keywords_required():
    with pytest.raises(ConfigError, match="keywords"):
        parse_config({"search": {}})


def test_unknown_key_is_reported():
    with pytest.raises(ConfigError, match="dry_run"):
        parse_config({"search": {"keywords": ["x"]}, "behavior": {"dryrun": True}})


def test_bad_delay_pair():
    with pytest.raises(ConfigError, match="delay_seconds"):
        parse_config({"search": {"keywords": ["x"]}, "limits": {"delay_seconds": [5, 1]}})


def test_missing_file_message(tmp_path):
    with pytest.raises(ConfigError, match="config.example.yaml"):
        load_config(tmp_path / "config.yaml")


def test_example_config_is_valid_yaml_with_all_sections():
    raw = yaml.safe_load((ROOT / "config.example.yaml").read_text())
    assert {"search", "filters", "limits", "behavior", "applicant", "answers"} <= raw.keys()
