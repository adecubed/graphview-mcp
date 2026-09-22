from graphview.masking import Masker


def test_masks_email_iban_ssn_and_phone():
    m = Masker()
    text = "Alice, alice.moore@example.com, GB29 NWBK 6016 1331 9268 19, 078-05-1120, +44 20 7946 0958"
    out = m.mask(text)
    for secret in ("alice.moore@example.com", "NWBK 6016", "078-05-1120", "7946 0958"):
        assert secret not in out
    assert out.startswith("Alice, ")


def test_plain_text_is_untouched():
    assert Masker().mask("Meeting notes 2026") == "Meeting notes 2026"


def test_custom_patterns_replace_defaults():
    m = Masker(patterns=[r"secret\w*"])
    assert m.mask("a secretplan, b@example.com") == "a ███, b@example.com"


def test_timestamps_and_dates_are_not_mistaken_for_phone_numbers():
    m = Masker()
    for text in ("2026-09-12T21:16:27.114390+00:00", "2026-09-12 21:16:27",
                 "2026-09-12", "seen 2026-09-12T21:16:27Z twice"):
        assert m.mask(text) == text


def test_a_phone_next_to_a_timestamp_is_still_masked():
    out = Masker().mask("2026-09-12T21:16:27+00:00 call 06 12345678")
    assert out.startswith("2026-09-12T21:16:27+00:00 call ")
    assert "12345678" not in out
