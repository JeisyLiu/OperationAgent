from app.services.playwright_browser import is_missing_browser_error


def test_is_missing_browser_error_detects_playwright_message():
    msg = "Executable doesn't exist at C:\\Users\\...\\chrome.exe\nPlease run playwright install"
    assert is_missing_browser_error(msg) is True
    assert is_missing_browser_error(RuntimeError(msg)) is True
    assert is_missing_browser_error("connection refused") is False
