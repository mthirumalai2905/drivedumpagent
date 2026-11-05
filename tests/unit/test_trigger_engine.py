from app.services.trigger_engine import message_matches


def test_subject_match_is_case_insensitive():
    assert message_matches("Back Office - November Invoice", "", ["back office"]) == "back office"


def test_body_match():
    matched = message_matches(
        "Monthly Update",
        "Please send this to the back office.",
        ["back office"],
    )
    assert matched == "back office"


def test_unrelated_email_is_ignored():
    assert message_matches("Personal Conversation", "See you tomorrow.", ["back office"]) is None


def test_partial_word_does_not_match():
    assert message_matches("Staff update", "The back officer will reply.", ["back office"]) is None


def test_multiple_keywords_return_the_first_match():
    matched = message_matches("Q4 pack", "Attached.", ["back office", "q4 pack"])
    assert matched == "q4 pack"


def test_empty_keyword_list_never_matches():
    assert message_matches("Back Office", "back office", []) is None
