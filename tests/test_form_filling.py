"""Drive the form-filling code in a real browser against a mock Easy Apply dialog.

Set CHROMIUM_PATH to use a specific Chromium binary instead of Playwright's bundled one.
"""

import os

import pytest

from linkedin_apply.answers import AnswerBank
from linkedin_apply.config import parse_config
from linkedin_apply.filters import JobInfo
from linkedin_apply.tracker import DRY_RUN, Tracker

sync_api = pytest.importorskip("playwright.sync_api")

MODAL = """
<html><body>
<button class="jobs-apply-button" onclick="document.getElementById('m').style.display='block'">Easy Apply</button>
<div id="m" class="jobs-easy-apply-modal" role="dialog" style="display:none">
  <button aria-label="Dismiss" onclick="document.getElementById('confirm').style.display='block'">x</button>
  <button id="confirm" data-control-name="discard_application_confirm_btn" style="display:none"
          onclick="window.discarded = true; document.getElementById('m').style.display='none'">Discard</button>
  <form>
   <section id="step1">
    <h3>Contact info</h3>
    <div data-test-form-element><label for="phone">Mobile phone number<span>Mobile phone number</span></label>
      <input id="phone" type="text" required></div>
    <div data-test-form-element><label for="email">Email</label>
      <input id="email" type="text" value="prefilled@example.com"></div>
   </section>
   <section id="step2" style="display:none">
    <h3>Additional questions</h3>
    <div data-test-form-element><label for="yrs">How many years of experience do you have with Python?</label>
      <input id="yrs" type="text" class="numeric" name="numeric-yrs" required></div>
    <fieldset data-test-form-builder-radio-button-form-component>
      <legend><span>Will you now or in the future require visa sponsorship?</span>
              <span>Will you now or in the future require visa sponsorship?</span></legend>
      <input type="radio" id="s-yes" name="s" value="Yes" required><label for="s-yes">Yes</label>
      <input type="radio" id="s-no" name="s" value="No" required><label for="s-no">No</label>
    </fieldset>
    <div data-test-form-element><label for="eng">What is your level of proficiency in English?</label>
      <select id="eng" required><option>Select an option</option><option>Basic</option>
      <option>Professional working proficiency</option><option>Native</option></select></div>
    <div data-test-form-element><label for="opt">Anything else? (optional)</label>
      <textarea id="opt"></textarea></div>
   </section>
   <section id="step3" style="display:none">
    <h3>Review</h3>
    <input type="checkbox" id="follow-company-checkbox" checked><label for="follow-company-checkbox">Follow</label>
   </section>
  </form>
  <footer><button id="primary" type="button" class="artdeco-button--primary" aria-label="Continue to next step"
     onclick="next()">Next</button></footer>
</div>
<script>
let step = 1;
function next() {
  document.getElementById('step' + step).style.display = 'none';
  step += 1;
  document.getElementById('step' + step).style.display = 'block';
  const b = document.getElementById('primary');
  if (step === 2) { b.setAttribute('aria-label', 'Review your application'); b.innerText = 'Review'; }
  if (step === 3) { b.setAttribute('aria-label', 'Submit application'); b.innerText = 'Submit'; }
}
</script>
</body></html>
"""

CONFIG = {
    "search": {"keywords": ["x"]},
    "limits": {"delay_seconds": 0, "between_applications_seconds": 0},
    "behavior": {"dry_run": True, "on_unknown_question": "skip"},
    "applicant": {"phone": "+62 812 0000"},
    "answers": [
        {"match": "years.*python", "answer": "3 years"},
        {"match": "sponsorship", "answer": "No"},
        {"match": "english", "answer": "Professional"},
    ],
}


@pytest.fixture
def page():
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        except Exception as exc:  # no browser installed
            pytest.skip(f"Chromium unavailable: {exc}")
        pg = browser.new_page()
        pg.set_content(MODAL)
        yield pg
        browser.close()


def make_bot(tmp_path, overrides=None):
    from linkedin_apply.bot import EasyApplyBot

    raw = {**CONFIG, **(overrides or {})}
    raw["files"] = {"tracker": str(tmp_path / "a.csv"), "unanswered": str(tmp_path / "q.csv"),
                    "screenshots_dir": str(tmp_path / "shots")}
    cfg = parse_config(raw)
    tracker = Tracker(cfg.files.tracker, cfg.files.unanswered)
    return EasyApplyBot(cfg, tracker, AnswerBank(cfg.answers, cfg.applicant), log=lambda *_: None)


def test_walks_all_steps_and_stops_before_submit_in_dry_run(page, tmp_path):
    bot = make_bot(tmp_path)
    status, _ = bot._apply(page, page.locator("button.jobs-apply-button"), JobInfo("1", title="Dev"))

    assert status == DRY_RUN
    assert page.input_value("#phone") == "+62 812 0000"
    assert page.input_value("#email") == "prefilled@example.com"  # prefilled values untouched
    assert page.input_value("#yrs") == "3"
    assert page.is_checked("#s-no")
    assert page.eval_on_selector("#eng", "s => s.value") == "Professional working proficiency"
    assert page.input_value("#opt") == ""  # optional + unknown -> left blank
    assert not page.is_checked("#follow-company-checkbox")
    assert page.evaluate("window.discarded") is True  # dry run discards instead of submitting


def test_unknown_required_question_discards_and_is_logged(page, tmp_path):
    from linkedin_apply.bot import NeedsAnswers

    bot = make_bot(tmp_path, {"answers": [{"match": "years.*python", "answer": "3"}]})
    with pytest.raises(NeedsAnswers) as exc:
        bot._apply(page, page.locator("button.jobs-apply-button"), JobInfo("1"))
    labels = [q.label for q in exc.value.questions]
    assert labels == [
        "Will you now or in the future require visa sponsorship?",
        "What is your level of proficiency in English?",
    ]
    assert exc.value.questions[1].options[1:] == ["Basic", "Professional working proficiency", "Native"]


def test_ask_mode_uses_terminal_answer_and_remembers_it(page, tmp_path):
    replies = iter(["2", "native"])
    bot = make_bot(tmp_path, {"answers": [{"match": "years.*python", "answer": "3"}],
                              "behavior": {"dry_run": True, "on_unknown_question": "ask"}})
    bot.prompt = lambda _msg: next(replies)
    status, _ = bot._apply(page, page.locator("button.jobs-apply-button"), JobInfo("1"))
    assert status == DRY_RUN
    assert page.is_checked("#s-no")
    assert page.eval_on_selector("#eng", "s => s.value") == "Native"
    assert bot.answers.learned["what is your level of proficiency in english?"] == "Native"
