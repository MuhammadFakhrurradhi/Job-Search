"""Read a resume (PDF or image) offline and pull out the fields the answer bank needs.

Text comes from the PDF's own text layer when it has one. Scanned pages and image files are
run through RapidOCR, whose ONNX models ship inside the pip package, so nothing is sent to a
server and no network connection is needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
# A page whose text layer has fewer characters than this is treated as scanned and OCR'd.
MIN_TEXT_CHARS = 30
RENDER_DPI = 300


class ResumeError(RuntimeError):
    pass


# --------------------------------------------------------------------------- text extraction

_ocr_engine = None


def _ocr():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise ResumeError(
                "OCR needs the optional dependencies: pip install -e '.[ocr]'"
            ) from exc
        _ocr_engine = RapidOCR()
    return _ocr_engine


def group_lines(items: list[tuple[list, str]]) -> list[str]:
    """Join OCR boxes ``(corner points, text)`` into reading-order lines.

    Boxes whose vertical centres are within half a box height of each other are on one line.
    """
    boxes = []
    for points, text in items:
        ys = [p[1] for p in points]
        xs = [p[0] for p in points]
        top, bottom = min(ys), max(ys)
        boxes.append(((top + bottom) / 2, max(bottom - top, 1), min(xs), text))
    boxes.sort()

    lines: list[list[tuple]] = []
    for box in boxes:
        if lines:
            centre = sum(b[0] for b in lines[-1]) / len(lines[-1])
            if abs(box[0] - centre) <= box[1] / 2:
                lines[-1].append(box)
                continue
        lines.append([box])
    return [" ".join(b[3] for b in sorted(line, key=lambda b: b[2])) for line in lines]


def ocr_image(image) -> str:
    """OCR an image (path, bytes, numpy array or PIL image) and return its text."""
    if hasattr(image, "convert"):  # PIL image
        import numpy as np

        image = np.array(image.convert("RGB"))[:, :, ::-1]  # RGB -> BGR for OpenCV
    result, _ = _ocr()(image)
    return "\n".join(group_lines([(box, text) for box, text, _score in result or []]))


def extract_text(path: str | Path, force_ocr: bool = False) -> str:
    """Return the text of a PDF or image file, using OCR only where it is needed."""
    path = Path(path)
    if not path.exists():
        raise ResumeError(f"{path} not found")
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return ocr_image(str(path))
    if suffix != ".pdf":
        raise ResumeError(f"unsupported file type {suffix!r}; use a PDF or an image")

    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ResumeError("reading PDFs needs: pip install -e '.[ocr]'") from exc

    pages = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for page in pdf:
            text = "" if force_ocr else page.get_textpage().get_text_range()
            if len(text.strip()) < MIN_TEXT_CHARS:
                text = ocr_image(page.render(scale=RENDER_DPI / 72).to_pil())
            pages.append(text)
    finally:
        pdf.close()
    return "\n".join(pages)


# --------------------------------------------------------------------------- field parsing


@dataclass
class ResumeInfo:
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    years_experience: int | None = None
    skipped: list[str] = field(default_factory=list)  # fields that could not be found


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<![\w/])(?:\+\d{1,3}[\s.-]?)?\(?\d{2,4}\)?(?:[\s.-]?\d{2,5}){2,4}(?!\w)")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([\w-]+)", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([\w-]+)", re.I)
URL_RE = re.compile(r"(?:https?://|www\.)[^\s|,;]+|\b[\w-]+\.(?:com|io|dev|me|net|org|id|co\.id)(?:/[^\s|,;]*)?\b", re.I)
YEARS_RE = re.compile(
    r"(\d{1,2})\+?\s*(?:years?|yrs?|tahun)\s*(?:of\s*)?(?:professional\s*|work(?:ing)?\s*|relevant\s*)?"
    r"(?:experience|pengalaman)",
    re.I,
)
CITY_RE = re.compile(r"^([A-Z][A-Za-z.' -]{1,30}),\s*([A-Z][A-Za-z.' -]{1,30})$")
SEPARATORS_RE = re.compile(r"\s*[|•·◦▪●♦,;]\s*|\s{3,}")

NAME_STOPWORDS = {
    "resume", "curriculum", "vitae", "cv", "profile", "summary", "contact", "about", "me",
    "riwayat", "hidup", "daftar",
}

EXPERIENCE_HEADINGS = re.compile(
    # \s* rather than \s+: OCR often drops the space in all-caps headings ("WORKEXPERIENCE")
    r"^\s*((work|professional|relevant)\s*)?(experience|employment|career)(\s*history)?\s*:?\s*$"
    r"|^\s*pengalaman(\s*(kerja|bekerja|profesional))?\s*:?\s*$",
    re.I,
)
OTHER_HEADINGS = re.compile(
    r"^\s*(education|skills?|technical\s*skills|projects?|certifications?|certificates?|awards?|"
    r"languages?|publications?|interests|hobbies|references|volunteer(ing)?(\s*experience)?|"
    r"organi[sz]ations?|achievements?|courses?|training|summary|profile|about\s*me|"
    r"pendidikan|keahlian|keterampilan|proyek|sertifikasi|bahasa|organisasi|prestasi)\s*:?\s*$",
    re.I,
)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "mei": 5, "jun": 6, "jul": 7,
    "aug": 8, "agu": 8, "agt": 8, "sep": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12, "des": 12,
}
_MONTH = r"(?:jan|feb|mar|apr|may|mei|jun|jul|aug|agu|agt|sep|oct|okt|nov|dec|des)[a-z]*\.?"
_POINT = rf"(?:{_MONTH}\s*\d{{4}}|\d{{1,2}}[/.-]\d{{4}}|\d{{4}})"
_PRESENT = r"(?:present|current|now|today|sekarang|saat\s*ini)"
RANGE_RE = re.compile(rf"({_POINT})\s*(?:-|–|—|to|until|s/?d|sampai|hingga)\s*({_POINT}|{_PRESENT})", re.I)


def _parse_point(text: str, today: date) -> tuple[int, int]:
    text = text.strip().lower()
    if re.fullmatch(_PRESENT, text):
        return today.year, today.month
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{4})", text)
    if m:
        return int(m.group(2)), max(1, min(12, int(m.group(1))))
    m = re.fullmatch(rf"({_MONTH})\s*(\d{{4}})", text)
    if m:
        return int(m.group(2)), MONTHS[m.group(1)[:3]]
    return int(text), 1


def experience_section(lines: list[str]) -> list[str]:
    """Lines under the work-experience heading, up to the next known heading."""
    out: list[str] = []
    inside = False
    for line in lines:
        if EXPERIENCE_HEADINGS.match(line):
            inside = True
            continue
        if inside and OTHER_HEADINGS.match(line):
            inside = False
        if inside:
            out.append(line)
    return out


def years_from_ranges(lines: list[str], today: date | None = None) -> int | None:
    """Total years covered by date ranges (overlaps merged), rounded down."""
    today = today or date.today()
    spans = []
    for line in lines:
        for start, end in RANGE_RE.findall(line):
            s_year, s_month = _parse_point(start, today)
            e_year, e_month = _parse_point(end, today)
            # a bare end year ("2019 - 2021") means the end of that year
            if re.fullmatch(r"\d{4}", end.strip()):
                e_month = 12
            s, e = s_year * 12 + s_month, e_year * 12 + e_month
            if 1950 <= s_year <= today.year and e >= s:
                spans.append((s, e))
    if not spans:
        return None
    spans.sort()
    months, (cur_s, cur_e) = 0, spans[0]
    for s, e in spans[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            months += cur_e - cur_s + 1
            cur_s, cur_e = s, e
    months += cur_e - cur_s + 1
    return months // 12


def _guess_name(lines: list[str]) -> tuple[str, str]:
    for line in lines[:4]:  # the name sits at the very top
        cleaned = SEPARATORS_RE.split(line.strip())[0].strip()
        words = cleaned.split()
        if not 2 <= len(words) <= 5:
            continue
        if any(w.lower().strip(":") in NAME_STOPWORDS for w in words):
            continue
        # names are capitalised words; this also rules out sentences like a summary line
        if not all(re.fullmatch(r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ.'-]*", w) for w in words):
            continue
        words = [w.capitalize() if w.isupper() or w.islower() else w for w in words]
        return words[0], " ".join(words[1:])
    # OCR can glue an all-caps name into one word ("BUDISANTOSO"); keep it whole for the user to split
    first = SEPARATORS_RE.split(lines[0].strip())[0].strip() if lines else ""
    if re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}", first) and first.lower() not in NAME_STOPWORDS:
        return first.capitalize() if first.isupper() else first, ""
    return "", ""


def _clean_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if not 9 <= len(digits) <= 15:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def parse_resume(text: str, today: date | None = None) -> ResumeInfo:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    info = ResumeInfo()

    info.first_name, info.last_name = _guess_name(lines)

    if m := EMAIL_RE.search(text):
        info.email = m.group(0).rstrip(".")
    if m := LINKEDIN_RE.search(text):
        info.linkedin = f"https://www.linkedin.com/in/{m.group(1)}"
    if m := GITHUB_RE.search(text):
        info.github = f"https://github.com/{m.group(1)}"

    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(".)")
        low = url.lower()
        if "linkedin.com" in low or "github.com" in low:
            continue
        if info.email and low in info.email.lower():  # domain part of the e-mail address
            continue
        info.website = url if low.startswith("http") else f"https://{url}"
        break

    # Look for a phone number in the contact block first, so dates and IDs further down
    # are not mistaken for one.
    for chunk in ("\n".join(lines[:15]), text):
        for m in PHONE_RE.finditer(chunk):
            if phone := _clean_phone(m.group(0)):
                info.phone = phone
                break
        if info.phone:
            break

    for line in lines[:15]:
        # split on separators other than the comma, which belongs inside "City, Country"
        for part in re.split(r"\s*[|•·◦▪●♦;]\s*|\s{3,}", line):
            part = part.strip()
            if "@" not in part and not re.search(r"\d", part) and (m := CITY_RE.match(part)):
                info.city = f"{m.group(1).strip()}, {m.group(2).strip()}"
                break
        if info.city:
            break

    stated = [int(n) for n in YEARS_RE.findall(text)]
    if stated:
        info.years_experience = max(stated)
    else:
        info.years_experience = years_from_ranges(experience_section(lines), today)

    for name in ("first_name", "email", "phone", "city", "linkedin", "years_experience"):
        if getattr(info, name) in ("", None):
            info.skipped.append(name)
    return info


# --------------------------------------------------------------------------- output


def to_config_yaml(info: ResumeInfo, resume_path: str = "") -> str:
    """A YAML snippet with ``applicant`` values and ``answers`` rules, ready to paste."""
    applicant = {
        key: value
        for key, value in {
            "first_name": info.first_name,
            "last_name": info.last_name,
            "email": info.email,
            "phone": info.phone,
            "city": info.city,
            "resume_path": resume_path,
            "default_years_experience": info.years_experience,
        }.items()
        if value not in ("", None)
    }
    answers = []
    if info.linkedin:
        answers.append({"match": "linkedin.*(profile|url)", "answer": info.linkedin})
    if info.github:
        answers.append({"match": "github", "answer": info.github})
    if info.website or info.github:
        answers.append({"match": "portfolio|website", "answer": info.website or info.github})
    if info.years_experience is not None:
        answers.append({"match": "years.*experience", "answer": str(info.years_experience)})

    data = {"applicant": applicant}
    if answers:
        data["answers"] = answers
    out = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    header = "# Extracted from your resume. Check every value before copying it into config.yaml.\n"
    if info.skipped:
        header += f"# Not found, fill in by hand: {', '.join(info.skipped)}\n"
    return header + out
