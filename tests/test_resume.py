from datetime import date

import pytest
import yaml

from linkedin_apply.resume import (
    experience_section,
    group_lines,
    parse_resume,
    to_config_yaml,
    years_from_ranges,
)

TODAY = date(2026, 10, 1)

RESUME = """\
BUDI SANTOSO
Jakarta, Indonesia | budi.santoso@gmail.com | +62 812 3456 7890
linkedin.com/in/budi-santoso | github.com/budisan | budi.dev

SUMMARY
Data analyst who likes clean pipelines.

WORK EXPERIENCE
Data Analyst, PT Maju        Mar 2021 - Present
Junior Analyst, PT Kecil     Jan 2019 - Feb 2021

EDUCATION
Universitas Indonesia        2014 - 2018
"""


def test_parse_contact_fields():
    info = parse_resume(RESUME, today=TODAY)
    assert (info.first_name, info.last_name) == ("Budi", "Santoso")
    assert info.email == "budi.santoso@gmail.com"
    assert info.phone == "+62 812 3456 7890"
    assert info.city == "Jakarta, Indonesia"
    assert info.linkedin == "https://www.linkedin.com/in/budi-santoso"
    assert info.github == "https://github.com/budisan"
    assert info.website == "https://budi.dev"
    assert info.skipped == []


def test_years_come_from_experience_section_only():
    # Jan 2019 .. Oct 2026 = 7 years 10 months; the 2014-2018 education range is ignored
    assert parse_resume(RESUME, today=TODAY).years_experience == 7


def test_stated_years_win_over_dates():
    assert parse_resume("Ana Lee\n5+ years of experience in SQL", today=TODAY).years_experience == 5


def test_indonesian_dates_and_headings():
    lines = [
        "PENGALAMAN KERJA",
        "Backend Engineer — Agustus 2020 – Sekarang",
        "Intern — 06/2019 - 12/2019",
        "PENDIDIKAN",
        "ITB 2015 - 2019",
    ]
    section = experience_section(lines)
    assert len(section) == 2
    assert years_from_ranges(section, TODAY) == 6


def test_ocr_glued_heading_is_recognised():
    assert experience_section(["WORKEXPERIENCE", "Dev 2020 - 2021", "EDUCATION", "x"]) == ["Dev 2020 - 2021"]


def test_overlapping_ranges_are_merged():
    assert years_from_ranges(["2018 - 2020", "2019 - 2021"], TODAY) == 4


def test_glued_ocr_name_kept_whole():
    info = parse_resume("BUDISANTOSO\nbudi@x.com", today=TODAY)
    assert (info.first_name, info.last_name) == ("Budisantoso", "")


def test_missing_fields_are_listed():
    info = parse_resume("Curriculum Vitae\nnothing useful here", today=TODAY)
    assert {"first_name", "email", "phone", "years_experience"} <= set(info.skipped)


def test_group_lines_orders_boxes_into_lines():
    def box(x, y, text):
        return ([[x, y], [x + 50, y], [x + 50, y + 20], [x, y + 20]], text)

    items = [box(200, 52, "Santoso"), box(10, 100, "Jakarta"), box(10, 50, "Budi")]
    assert group_lines(items) == ["Budi Santoso", "Jakarta"]


def test_config_yaml_snippet_is_valid_config():
    snippet = to_config_yaml(parse_resume(RESUME, today=TODAY), resume_path="cv.pdf")
    data = yaml.safe_load(snippet)
    assert data["applicant"]["email"] == "budi.santoso@gmail.com"
    assert data["applicant"]["default_years_experience"] == 7
    assert data["applicant"]["resume_path"] == "cv.pdf"
    matches = {rule["match"]: rule["answer"] for rule in data["answers"]}
    assert matches["linkedin.*(profile|url)"] == "https://www.linkedin.com/in/budi-santoso"


def test_ocr_reads_rendered_text():
    pytest.importorskip("rapidocr_onnxruntime")
    PIL = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw, ImageFont

    from linkedin_apply.resume import ocr_image

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        font = ImageFont.load_default(size=40)
    img = Image.new("RGB", (900, 120), "white")
    ImageDraw.Draw(img).text((20, 30), "jane.doe@example.com", fill="black", font=font)
    assert "jane.doe@example.com" in ocr_image(img).replace(" ", "")
