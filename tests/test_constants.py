from app.constants import FailureCode, classify_failure


def test_classify_login_required():
    assert classify_failure("Please sign in to continue") == FailureCode.LOGIN_REQUIRED.value


def test_classify_captcha():
    assert classify_failure("Captcha verification required") == FailureCode.CAPTCHA_BLOCKED.value


def test_classify_unknown():
    assert classify_failure("Something else happened") == FailureCode.UNKNOWN.value
