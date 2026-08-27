from unittest.mock import MagicMock, patch

import pytest

from app.services.web_search_service import WebSearchResult, WebSearchService, web_search_service


@pytest.fixture
def svc():
    return WebSearchService()


def test_search_site_builds_site_query_and_filters(svc):
    raw_rows = [
        {"href": "https://www.bilibili.com/video/BV1", "title": "视频一", "body": "描述一"},
        {"href": "https://search.bilibili.com/all?keyword=x", "title": "搜索页", "body": ""},
        {"href": "https://www.bilibili.com/", "title": "首页", "body": ""},
        {"href": "https://example.com/video/1", "title": "外站", "body": ""},
        {"href": "https://www.bilibili.com/video/BV1", "title": "重复", "body": ""},
    ]

    with patch("app.services.web_search_service._ddg_text_search", return_value=raw_rows) as mock_ddg:
        hits = svc.search_site("bilibili.com", "测评", max_results=5)

    mock_ddg.assert_called_once()
    assert mock_ddg.call_args[0][0] == "site:bilibili.com 测评"
    assert len(hits) == 1
    assert hits[0].url == "https://www.bilibili.com/video/BV1"
    assert hits[0].title == "视频一"


def test_search_returns_empty_on_ddg_failure(svc):
    with patch("app.services.web_search_service._ddg_text_search", side_effect=RuntimeError("network")):
        assert svc.search("hello") == []


def test_search_site_empty_keyword(svc):
    assert svc.search_site("", "tag") == []
    assert svc.search_site("bilibili.com", "") == []


def test_web_search_service_singleton():
    assert web_search_service is not None


def test_is_content_url_bilibili_video():
    from app.services.web_search_service import _is_content_url

    assert _is_content_url("https://www.bilibili.com/video/BV1", "bilibili.com")
    assert not _is_content_url("https://search.bilibili.com/all?keyword=x", "bilibili.com")
    assert not _is_content_url("https://www.bilibili.com/", "bilibili.com")
