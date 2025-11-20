from app.email_utils import generate_6_digit_code


def test_generate_6_digit_code_format():
    codes = {generate_6_digit_code() for _ in range(100)}
    assert all(code.isdigit() and len(code) == 6 for code in codes)
    # Ensure we get a reasonable spread of unique values.
    assert len(codes) > 1
