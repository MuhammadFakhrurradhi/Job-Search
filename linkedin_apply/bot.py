"""Browser automation: search LinkedIn, open jobs and walk the Easy Apply form.

LinkedIn changes its markup often. All selectors live in ``SEL`` so they are
easy to update when something stops matching.
"""

from __future__ import annotations

import random
import re
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import BrowserContext, Locator, Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

from .answers import AnswerBank, Question, normalize, pick_option, real_options
from .config import Config
from .filters import JobFilter, JobInfo
from .search import build_search_url, extract_job_id, job_url
from .tracker import APPLIED, DRY_RUN, FAILED, NEEDS_ANSWERS, SKIPPED, Tracker

FEED_URL = "https://www.linkedin.com/feed/"
LOGIN_URL = "https://www.linkedin.com/login"

SEL = {
    "logged_in": "#global-nav, header.global-nav",
    "result_cards": "li[data-occludable-job-id], div.job-card-container[data-job-id]",
    "card_title": "a.job-card-list__title, a.job-card-container__link, a[href*='/jobs/view/']",
    "card_company": ".artdeco-entity-lockup__subtitle, .job-card-container__primary-description",
    "no_results": ".jobs-search-no-results-banner, .jobs-search-two-pane__no-results-banner--expand",
    "job_title": ".job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, h1",
    "job_company": ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name",
    "job_location": ".job-details-jobs-unified-top-card__primary-description-container, "
    ".job-details-jobs-unified-top-card__tertiary-description-container",
    "job_description": "#job-details, .jobs-description__content, .jobs-description",
    "easy_apply_button": "button.jobs-apply-button:has-text('Easy Apply'), "
    "button[aria-label*='Easy Apply']",
    "modal": "div.jobs-easy-apply-modal, div[data-test-modal][role='dialog'], div[role='dialog']",
    "primary_button": "footer button.artdeco-button--primary, button[data-easy-apply-next-button], "
    "button[aria-label='Submit application'], button[aria-label='Review your application'], "
    "button[aria-label='Continue to next step']",
    "field_error": ".artdeco-inline-feedback--error",
    "follow_company": "input#follow-company-checkbox",
    "dismiss": "button[aria-label='Dismiss']",
    "discard_confirm": "button[data-control-name='discard_application_confirm_btn'], "
    "button[data-test-dialog-secondary-btn], button:has-text('Discard')",
    "typeahead_option": "[role='listbox'] [role='option'], .basic-typeahead__selectable",
}

LIMIT_TEXT = re.compile(r"reached (the|your) (daily )?(easy apply )?(application )?limit", re.I)
MAX_FORM_STEPS = 12


class StopRun(Exception):
    """Raised to end the whole run (user quit or LinkedIn application limit)."""


class NeedsAnswers(Exception):
    def __init__(self, questions: list[Question]):
        super().__init__(", ".join(q.label for q in questions))
        self.questions = questions


# JS helpers ---------------------------------------------------------------

# Returns a readable label for a form control. LinkedIn often duplicates label
# text inside visually-hidden spans, so repeated lines are collapsed.
_LABEL_JS = """
(el) => {
  const clean = (t) => {
    const seen = new Set(); const out = [];
    for (const line of (t || '').split('\\n').map(s => s.trim()).filter(Boolean)) {
      if (!seen.has(line)) { seen.add(line); out.push(line); }
    }
    const text = out.join(' ');
    // "Question? Question?" (same text in a visible and a hidden span) -> "Question?"
    const half = (text.length - 1) / 2;
    if (Number.isInteger(half) && text[half] === ' ' && text.slice(0, half) === text.slice(half + 1)) {
      return text.slice(0, half);
    }
    return text;
  };
  if (el.tagName === 'FIELDSET') {
    const legend = el.querySelector('legend');
    return clean(legend ? legend.innerText : el.getAttribute('aria-label'));
  }
  if (el.labels && el.labels.length) return clean(el.labels[0].innerText);
  if (el.getAttribute('aria-label')) return clean(el.getAttribute('aria-label'));
  const group = el.closest('[data-test-form-element], .jobs-easy-apply-form-section__grouping, .fb-dash-form-element');
  const lab = group && group.querySelector('label, legend, span.t-bold');
  return clean(lab ? lab.innerText : '');
}
"""

_REQUIRED_JS = """
(el) => {
  if (el.required || el.getAttribute('aria-required') === 'true') return true;
  if (el.querySelector && el.querySelector('[required], [aria-required="true"]')) return true;
  const group = el.closest('[data-test-form-element], .jobs-easy-apply-form-section__grouping, .fb-dash-form-element');
  return !!(group && /required/i.test(group.innerText));
}
"""


def _strip_required(label: str) -> str:
    return re.sub(r"\s*\b[Rr]equired\b\s*$", "", label).strip()


class EasyApplyBot:
    def __init__(
        self,
        cfg: Config,
        tracker: Tracker,
        answers: AnswerBank,
        prompt: Callable[[str], str] = input,
        log: Callable[[str], None] = print,
    ):
        self.cfg = cfg
        self.tracker = tracker
        self.answers = answers
        self.filter = JobFilter(cfg.filters)
        self.prompt = prompt
        self.log = log
        self.applied = 0

    # ------------------------------------------------------------------ setup

    def _launch(self, pw, headless: bool) -> BrowserContext:
        return pw.chromium.launch_persistent_context(
            user_data_dir=str(Path(self.cfg.profile_dir).resolve()),
            headless=headless,
            viewport={"width": 1280, "height": 900},
        )

    def login(self) -> None:
        """Open a visible browser and wait for the user to log in manually."""
        with sync_playwright() as pw:
            ctx = self._launch(pw, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(FEED_URL)
            if not self._is_logged_in(page):
                page.goto(LOGIN_URL)
                self.log("Log in to LinkedIn in the browser window (including any 2FA). Waiting up to 5 minutes...")
                page.wait_for_selector(SEL["logged_in"], timeout=300_000)
            self.log(f"Logged in. Session saved to {self.cfg.profile_dir}")
            ctx.close()

    def _is_logged_in(self, page: Page) -> bool:
        if re.search(r"/(login|authwall|checkpoint|uas/)", page.url):
            return False
        try:
            page.wait_for_selector(SEL["logged_in"], timeout=8_000)
            return True
        except PWTimeout:
            return False

    def _pause(self, bounds: tuple[float, float] | None = None) -> None:
        lo, hi = bounds or self.cfg.limits.delay_seconds
        time.sleep(random.uniform(lo, hi))

    # -------------------------------------------------------------------- run

    def run(self) -> None:
        with sync_playwright() as pw:
            ctx = self._launch(pw, headless=self.cfg.headless)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(FEED_URL)
                if not self._is_logged_in(page):
                    raise StopRun("Not logged in — run `linkedin-apply login` first.")
                for keyword in self.cfg.search.keywords:
                    self._run_keyword(page, keyword)
            except StopRun as exc:
                self.log(f"Stopping: {exc}")
            finally:
                ctx.close()
        self.log(f"Done. Applications submitted this run: {self.applied}")

    def _limit_reached(self) -> bool:
        return self.applied >= self.cfg.limits.max_applications_per_run

    def _run_keyword(self, page: Page, keyword: str) -> None:
        for page_no in range(self.cfg.limits.max_pages_per_search):
            if self._limit_reached():
                raise StopRun(f"reached max_applications_per_run ({self.applied})")
            url = build_search_url(self.cfg.search, keyword, page_no)
            self.log(f"\n== '{keyword}' page {page_no + 1}: {url}")
            listings = self._collect_listings(page, url)
            if not listings:
                self.log("No (more) results.")
                return
            for job in listings:
                if self._limit_reached():
                    raise StopRun(f"reached max_applications_per_run ({self.applied})")
                self._process_job(page, job)

    def _collect_listings(self, page: Page, url: str) -> list[JobInfo]:
        page.goto(url)
        self._pause()
        if page.locator(SEL["no_results"]).count():
            return []
        cards = page.locator(SEL["result_cards"])
        jobs: dict[str, JobInfo] = {}
        # Cards are rendered lazily: scroll each into view before reading it.
        for i in range(cards.count()):
            card = cards.nth(i)
            try:
                card.scroll_into_view_if_needed(timeout=3_000)
            except PWTimeout:
                continue
            job_id = card.get_attribute("data-occludable-job-id") or card.get_attribute("data-job-id")
            title_el = card.locator(SEL["card_title"]).first
            if not job_id and title_el.count():
                job_id = extract_job_id(title_el.get_attribute("href") or "")
            if not job_id or job_id in jobs:
                continue
            title = title_el.inner_text().split("\n")[0].strip() if title_el.count() else ""
            company_el = card.locator(SEL["card_company"]).first
            company = company_el.inner_text().strip() if company_el.count() else ""
            jobs[job_id] = JobInfo(job_id=job_id, title=title, company=company, url=job_url(job_id))
        self.log(f"Found {len(jobs)} listings.")
        return list(jobs.values())

    def _process_job(self, page: Page, job: JobInfo) -> None:
        if self.tracker.already_handled(job.job_id):
            return
        label = f"{job.title or job.job_id} @ {job.company or '?'}"
        reason = self.filter.check_listing(job)
        if reason:
            self.log(f"  skip  {label}: {reason}")
            self.tracker.record(job, SKIPPED, reason)
            return

        page.goto(job.url)
        self._pause()
        self._read_details(page, job)
        label = f"{job.title} @ {job.company}"
        reason = self.filter.check(job)
        if reason:
            self.log(f"  skip  {label}: {reason}")
            self.tracker.record(job, SKIPPED, reason)
            return

        button = page.locator(SEL["easy_apply_button"]).first
        if not button.count() or not button.is_visible():
            self.log(f"  skip  {label}: no Easy Apply button (already applied or external)")
            self.tracker.record(job, SKIPPED, "no Easy Apply button")
            return

        self.log(f"  apply {label}")
        try:
            status, detail = self._apply(page, button, job)
        except StopRun:
            self._discard(page)
            raise
        except NeedsAnswers as exc:
            for q in exc.questions:
                self.tracker.record_unanswered(job.job_id, q.label, q.kind, q.options)
            self._discard(page)
            status, detail = NEEDS_ANSWERS, f"unanswered: {exc}"
        except Exception as exc:  # keep going with the next job
            self._screenshot(page, job.job_id)
            self._discard(page)
            status, detail = FAILED, f"{type(exc).__name__}: {exc}"

        self.log(f"        -> {status}{': ' + detail if detail else ''}")
        self.tracker.record(job, status, detail)
        if status == APPLIED:
            self.applied += 1
            self._pause(self.cfg.limits.between_applications_seconds)

    def _read_details(self, page: Page, job: JobInfo) -> None:
        def text(selector: str) -> str:
            el = page.locator(selector).first
            try:
                return el.inner_text(timeout=5_000).strip() if el.count() else ""
            except PWTimeout:
                return ""

        job.title = text(SEL["job_title"]) or job.title
        job.company = text(SEL["job_company"]) or job.company
        job.location = text(SEL["job_location"]).split("·")[0].strip()
        job.description = text(SEL["job_description"])

    # ------------------------------------------------------------ easy apply

    def _apply(self, page: Page, button: Locator, job: JobInfo) -> tuple[str, str]:
        button.click()
        modal = page.locator(SEL["modal"]).first
        try:
            modal.wait_for(state="visible", timeout=10_000)
        except PWTimeout:
            if LIMIT_TEXT.search(page.inner_text("body")):
                raise StopRun("LinkedIn says the daily Easy Apply limit was reached")
            raise RuntimeError("Easy Apply dialog did not open")

        last_heading = None
        repeats = 0
        for _ in range(MAX_FORM_STEPS):
            self._pause((0.8, 1.8))
            if LIMIT_TEXT.search(modal.inner_text()):
                raise StopRun("LinkedIn says the daily Easy Apply limit was reached")

            self._fill_step(modal, job)
            primary = modal.locator(SEL["primary_button"]).last
            action = normalize(primary.get_attribute("aria-label") or primary.inner_text())

            if "submit" in action:
                return self._submit(page, modal, primary, job)

            primary.click()
            self._pause((1.0, 2.0))

            # Still on the same step with validation errors -> give up on this job.
            heading = modal.locator("h3, h2").first.inner_text() if modal.locator("h3, h2").count() else ""
            errors = modal.locator(SEL["field_error"])
            if errors.count() and errors.first.is_visible():
                repeats = repeats + 1 if heading == last_heading else 1
                if repeats >= 2:
                    raise RuntimeError(f"form rejected answers: {errors.first.inner_text().strip()}")
            last_heading = heading
        raise RuntimeError(f"gave up after {MAX_FORM_STEPS} form steps")

    def _submit(self, page: Page, modal: Locator, submit: Locator, job: JobInfo) -> tuple[str, str]:
        if self.cfg.behavior.unfollow_company:
            follow = modal.locator(SEL["follow_company"])
            if follow.count() and follow.is_checked():
                modal.locator("label[for='follow-company-checkbox']").click()

        if self.cfg.behavior.dry_run:
            self._discard(page)
            return DRY_RUN, "filled every step, did not submit"

        if self.cfg.behavior.review_before_submit:
            reply = self.prompt(f"        Submit application to '{job.title}' at {job.company}? [y/N/q] ").strip().lower()
            if reply == "q":
                raise StopRun("user quit")
            if reply != "y":
                self._discard(page)
                return SKIPPED, "declined at review"

        submit.click()
        self._pause((2.0, 4.0))
        dismiss = page.locator(SEL["dismiss"]).first
        if dismiss.count() and dismiss.is_visible():
            dismiss.click()
        return APPLIED, ""

    def _discard(self, page: Page) -> None:
        try:
            dismiss = page.locator(SEL["dismiss"]).first
            if dismiss.count() and dismiss.is_visible():
                dismiss.click(timeout=3_000)
                confirm = page.locator(SEL["discard_confirm"]).first
                confirm.wait_for(state="visible", timeout=3_000)
                confirm.click()
        except PWTimeout:
            pass

    def _screenshot(self, page: Page, job_id: str) -> None:
        folder = Path(self.cfg.files.screenshots_dir)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(folder / f"{job_id}-{int(time.time())}.png"))
        except Exception:
            pass

    # ------------------------------------------------------------ form fields

    def _fill_step(self, modal: Locator, job: JobInfo) -> None:
        unknown: list[Question] = []
        self._upload_resume(modal)

        for fieldset in modal.locator("fieldset").all():
            if not fieldset.is_visible():
                continue
            radios = fieldset.locator("input[type='radio']")
            boxes = fieldset.locator("input[type='checkbox']")
            if radios.count():
                self._fill_choice(fieldset, radios, "radio", job, unknown)
            elif boxes.count():
                self._fill_choice(fieldset, boxes, "checkbox", job, unknown)

        for select in modal.locator("select").all():
            if not select.is_visible():
                continue
            current = select.evaluate("s => s.options[s.selectedIndex] ? s.options[s.selectedIndex].text : ''")
            if real_options([current]):
                continue
            options = [o.strip() for o in select.locator("option").all_inner_texts()]
            q = self._question(select, "select", options)
            answer = self._resolve(q, select, job, unknown)
            if answer:
                select.select_option(label=answer)

        text_fields = modal.locator(
            "input[type='text'], input[type='tel'], input[type='email'], input[type='number'], "
            "input:not([type]), textarea"
        )
        for field in text_fields.all():
            if not field.is_visible() or field.input_value().strip():
                continue
            tag = field.evaluate("e => e.tagName.toLowerCase()")
            kind = "textarea" if tag == "textarea" else ("number" if self._is_numeric(field) else "text")
            q = self._question(field, kind, [])
            answer = self._resolve(q, field, job, unknown)
            if answer:
                field.fill(answer)
                if field.get_attribute("role") == "combobox" or field.get_attribute("aria-autocomplete"):
                    self._pick_typeahead(modal, field)

        if unknown:
            raise NeedsAnswers(unknown)

    def _fill_choice(self, fieldset: Locator, inputs: Locator, kind: str, job: JobInfo, unknown: list) -> None:
        if any(inputs.nth(i).is_checked() for i in range(inputs.count())):
            return
        labels = {}
        for i in range(inputs.count()):
            inp = inputs.nth(i)
            text = inp.evaluate("e => (e.labels && e.labels[0] ? e.labels[0].innerText : e.value) || ''")
            labels[text.strip().split("\n")[0].strip()] = inp
        q = self._question(fieldset, kind, list(labels))
        answer = self._resolve(q, fieldset, job, unknown)
        if answer:
            target = labels[answer]
            input_id = target.get_attribute("id")
            if input_id:
                fieldset.locator(f"label[for='{input_id}']").click()
            else:
                target.check(force=True)

    def _question(self, el: Locator, kind: str, options: list[str]) -> Question:
        return Question(label=_strip_required(el.evaluate(_LABEL_JS)), kind=kind, options=options)

    def _resolve(self, q: Question, el: Locator, job: JobInfo, unknown: list) -> str | None:
        answer = self.answers.answer(q)
        if answer is not None:
            return answer
        if not el.evaluate(_REQUIRED_JS):
            return None
        if self.cfg.behavior.on_unknown_question == "ask":
            answer = self._ask(q)
            if answer is not None:
                return answer
        unknown.append(q)
        return None

    def _ask(self, q: Question) -> str | None:
        self.log(f"\n        ? No answer for: {q.label!r} ({q.kind})")
        options = real_options(q.options)
        for i, opt in enumerate(options, 1):
            self.log(f"            {i}. {opt}")
        reply = self.prompt("          Answer (number/text, blank = skip this job): ").strip()
        if not reply:
            return None
        if options:
            if reply.isdigit() and 1 <= int(reply) <= len(options):
                reply = options[int(reply) - 1]
            chosen = pick_option(reply, options)
            if chosen is None:
                self.log("          Not one of the options — skipping this job.")
                return None
            reply = chosen
        self.answers.remember(q.label, reply)
        self.log("          (tip: add this to the answers section of config.yaml to reuse it next run)")
        return reply

    @staticmethod
    def _is_numeric(field: Locator) -> bool:
        if field.get_attribute("type") == "number":
            return True
        ident = (field.get_attribute("id") or "") + (field.get_attribute("name") or "")
        return "numeric" in ident.lower()

    def _pick_typeahead(self, modal: Locator, field: Locator) -> None:
        option = modal.page.locator(SEL["typeahead_option"]).first
        try:
            option.wait_for(state="visible", timeout=3_000)
            option.click()
        except PWTimeout:
            field.press("ArrowDown")
            field.press("Enter")

    def _upload_resume(self, modal: Locator) -> None:
        path = self.cfg.applicant.resume_path
        if not path:
            return
        uploads = modal.locator("input[type='file']")
        if not uploads.count():
            return
        resume = Path(path).expanduser()
        if not resume.exists():
            raise RuntimeError(f"resume_path {resume} does not exist")
        uploads.first.set_input_files(str(resume))
