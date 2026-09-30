from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd_with_leading_zero() -> None:
    out = scrub_text("CCCD: 001203004567")
    assert "001203004567" not in out
    assert "[REDACTED_CCCD]" in out
    assert "REDACTED_PHONE_VN" not in out


def test_scrub_credit_card_formats() -> None:
    for card in ("4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111"):
        out = scrub_text(f"Card: {card}")
        assert card not in out
        assert out == "Card: [REDACTED_CREDIT_CARD]"


def test_scrub_vietnamese_passport() -> None:
    out = scrub_text("Passport B1234567 expires soon")
    assert "B1234567" not in out
    assert "[REDACTED_PASSPORT_VN]" in out


def test_scrub_all_pii_types_in_one_sentence() -> None:
    raw = {
        "email": "test.user@example.com",
        "phone": "0912 345 678",
        "cccd": "001203004567",
        "card": "4111 1111 1111 1111",
    }
    out = scrub_text(
        f"Email {raw['email']}, phone {raw['phone']}, CCCD {raw['cccd']}, card {raw['card']}"
    )
    for value in raw.values():
        assert value not in out
    for label in ("EMAIL", "PHONE_VN", "CCCD", "CREDIT_CARD"):
        assert f"[REDACTED_{label}]" in out
