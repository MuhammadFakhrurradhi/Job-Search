from linkedin_apply.answers import AnswerBank, Question, pick_option
from linkedin_apply.config import AnswerRule, Applicant


def bank(rules=(), **applicant):
    return AnswerBank([AnswerRule(m, a) for m, a in rules], Applicant(**applicant))


def test_pick_option_prefers_exact_then_prefix_then_substring():
    opts = ["Select an option", "Yes, I am", "Yes", "No"]
    assert pick_option("yes", opts) == "Yes"
    assert pick_option("no", opts) == "No"
    assert pick_option("Native", ["Native or bilingual", "Professional"]) == "Native or bilingual"
    assert pick_option("maybe", opts) is None
    assert pick_option("select an option", opts) is None


def test_first_matching_rule_wins():
    b = bank([("years.*python", "5"), ("years", "2")])
    assert b.answer(Question("How many years of experience do you have with Python?", "number", [])) == "5"
    assert b.answer(Question("How many years of work experience?", "number", [])) == "2"


def test_number_fields_get_digits_only():
    b = bank([("salary", "IDR 15,000,000")])
    assert b.answer(Question("Expected salary", "number", [])) == "15000000"
    assert b.answer(Question("Expected salary", "text", [])) == "IDR 15,000,000"


def test_choice_answer_is_mapped_to_option_text():
    b = bank([("sponsorship", "no")])
    q = Question("Will you require visa sponsorship?", "radio", ["Yes", "No"])
    assert b.answer(q) == "No"


def test_choice_without_matching_option_is_unknown():
    b = bank([("english", "Fluent")])
    assert b.answer(Question("English level", "select", ["Select an option", "Basic", "Advanced"])) is None


def test_profile_fields_and_years_default():
    b = bank(first_name="Ana", phone="+62 812", default_years_experience=4)
    assert b.answer(Question("First name", "text", [])) == "Ana"
    assert b.answer(Question("Mobile phone number", "text", [])) == "+62 812"
    assert b.answer(Question("How many years of Kubernetes experience?", "number", [])) == "4"
    assert b.answer(Question("Why do you want this job?", "textarea", [])) is None


def test_default_yes_no_only_for_yes_no_choices():
    b = bank(default_yes_no="Yes")
    assert b.answer(Question("Are you comfortable commuting?", "radio", ["Yes", "No"])) == "Yes"
    assert b.answer(Question("Pick a shift", "select", ["Select an option", "Day", "Night"])) is None
    assert bank().answer(Question("Commute?", "radio", ["Yes", "No"])) is None


def test_learned_answers_take_priority():
    b = bank([("relocate", "No")])
    b.remember("Are you willing to relocate?", "Yes")
    assert b.answer(Question("Are you  willing to relocate?", "radio", ["Yes", "No"])) == "Yes"
