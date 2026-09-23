from urllib.parse import parse_qs, urlparse

import pytest

from linkedin_apply.config import SearchConfig
from linkedin_apply.search import build_search_url, extract_job_id


def params(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_full_search_url():
    cfg = SearchConfig(
        keywords=["x"],
        location="Indonesia",
        workplace=["remote", "hybrid"],
        experience=["entry", "mid_senior"],
        job_types=["full_time", "contract"],
        date_posted="past_week",
    )
    p = params(build_search_url(cfg, "Data Analyst", page=2))
    assert p == {
        "keywords": "Data Analyst",
        "location": "Indonesia",
        "f_AL": "true",
        "f_TPR": "r604800",
        "f_E": "2,4",
        "f_JT": "F,C",
        "f_WT": "2,3",
        "sortBy": "DD",
        "start": "50",
    }


def test_minimal_url_has_no_optional_filters():
    cfg = SearchConfig(keywords=["x"], easy_apply_only=False, sort_by_recent=False)
    assert params(build_search_url(cfg, "dev")) == {"keywords": "dev"}


def test_unknown_filter_value_raises():
    with pytest.raises(ValueError, match="workplace"):
        build_search_url(SearchConfig(keywords=["x"], workplace=["moon"]), "dev")


@pytest.mark.parametrize(
    "href,expected",
    [
        ("/jobs/view/3912345678/?refId=abc", "3912345678"),
        ("https://www.linkedin.com/jobs/search/?currentJobId=42&keywords=x", "42"),
        ("/company/foo", None),
        ("", None),
    ],
)
def test_extract_job_id(href, expected):
    assert extract_job_id(href) == expected
