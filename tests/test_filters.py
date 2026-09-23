from linkedin_apply.config import FilterConfig
from linkedin_apply.filters import JobFilter, JobInfo


def make_filter(**kw):
    return JobFilter(FilterConfig(**kw))


def test_title_exclude_is_case_insensitive_regex():
    f = make_filter(title_exclude=[r"\bsenior\b"])
    assert f.check(JobInfo("1", title="Senior Data Analyst")) is not None
    assert f.check(JobInfo("2", title="Data Analyst (Seniority flexible)")) is None


def test_title_include_requires_a_match():
    f = make_filter(title_include=["analyst", "python"])
    assert f.check(JobInfo("1", title="Python Developer")) is None
    assert "title_include" in f.check(JobInfo("2", title="Sales Rep"))


def test_company_exclude_ignores_case_and_whitespace():
    f = make_filter(company_exclude=["Acme Staffing"])
    assert f.check(JobInfo("1", title="Dev", company="  acme staffing ")) is not None


def test_description_only_checked_in_full_check():
    f = make_filter(description_exclude=["security clearance"])
    job = JobInfo("1", title="Dev", description="Requires active Security Clearance")
    assert f.check_listing(job) is None
    assert "description" in f.check(job)
