"""Tests for UrlProcessor — URL normalization, validation, and filtering."""
import pytest
from sitemap_comparison import UrlProcessor, Config, SKIP_EXTENSIONS
import argparse


class TestNormalizeUrl:
    """URL normalization strips fragments, trailing slashes, query params, lowercases domain."""

    @pytest.mark.parametrize("input_url, expected", [
        # Trailing slash removal
        ("https://www.example.com/about/", "https://www.example.com/about"),
        ("https://www.example.com/", "https://www.example.com/"),
        # Domain lowercasing
        ("https://www.EXAMPLE.COM/About", "https://www.example.com/about"),
        ("HTTPS://WWW.EXAMPLE.COM/Path", "https://www.example.com/path"),
        # Query string stripping
        ("https://www.example.com/page?utm_source=foo", "https://www.example.com/page"),
        ("https://www.example.com/page?page=2&ref=nav", "https://www.example.com/page"),
        # Fragment stripping
        ("https://www.example.com/page#section", "https://www.example.com/page"),
        ("https://www.example.com/page#", "https://www.example.com/page"),
        # Combined
        ("https://www.EXAMPLE.COM/About/?utm=foo#top", "https://www.example.com/about"),
        # No path (just domain)
        ("https://www.example.com", "https://www.example.com/"),
        # Empty path edge case
        ("https://www.example.com/", "https://www.example.com/"),
        # Subdomain preservation
        ("https://blog.example.com/post/123/", "https://blog.example.com/post/123"),
    ])
    def test_normalize(self, url_processor, input_url, expected):
        assert url_processor.normalize_url(input_url) == expected

    def test_normalize_different_domains_kept(self, url_processor):
        """Different domains should not be merged."""
        a = url_processor.normalize_url("https://www.example.com/page")
        b = url_processor.normalize_url("https://blog.example.com/page")
        assert a != b


class TestIsValidUrl:
    """URL validation: skip binary files, tracking query params, empty URLs."""

    @pytest.mark.parametrize("url, expected", [
        # Valid HTML pages
        ("https://www.example.com/about", True),
        ("https://www.example.com/", True),
        ("https://www.example.com/news/article", True),
        # Binary/file extensions to skip
        ("https://www.example.com/style.css", False),
        ("https://www.example.com/photo.jpg", False),
        ("https://www.example.com/doc.pdf", False),
        ("https://www.example.com/script.js", False),
        ("https://www.example.com/image.png", False),
        ("https://www.example.com/font.woff2", False),
        ("https://www.example.com/data.json", False),
        ("https://www.example.com/archive.zip", False),
        ("https://www.example.com/video.mp4", False),
        # Programming files
        ("https://www.example.com/script.py", False),
        ("https://www.example.com/config.yaml", False),
        # Tracking query params
        ("https://www.example.com/page?replytocom=5", False),
        ("https://www.example.com/page?share=twitter", False),
        ("https://www.example.com/page?like=yes", False),
        ("https://www.example.com/page?print=true", False),
        # Empty/invalid
        ("", False),
        (None, False),
    ])
    def test_is_valid(self, url_processor, url, expected):
        assert url_processor.is_valid_url(url) == expected

    def test_extension_case_insensitive(self, url_processor):
        """Extension check should be case-insensitive."""
        assert url_processor.is_valid_url("https://www.example.com/photo.JPG") is False
        assert url_processor.is_valid_url("https://www.example.com/photo.PNG") is False


class TestIsPaginationUrl:
    """Pagination URL detection — must NOT match legitimate content URLs."""

    @pytest.mark.parametrize("url, expected", [
        # Real pagination
        ("https://www.example.com/news/page/2/", True),
        ("https://www.example.com/news/page/2", True),
        ("https://www.example.com/news/page-3/", True),
        ("https://www.example.com/news/p/5/", True),
        ("https://www.example.com/news?page=2", True),
        ("https://www.example.com/news?p=3", True),
        ("https://www.example.com/news?paged=4", True),
        ("https://www.example.com/news?pg=2", True),
        ("https://www.example.com/news?offset=20", True),
        ("https://www.example.com/news?start=10", True),
        ("https://www.example.com/news?from=10", True),
        ("https://www.example.com/news?category=5&page=2", True),
        # NOT pagination (these are real content)
        ("https://www.example.com/news/article-title", False),
        ("https://www.example.com/about", False),
        ("https://www.example.com/", False),
        # Year/numeric paths should NOT match (was a bug — r'/\d+/?$')
        ("https://www.example.com/events/2024/", False),
        ("https://www.example.com/news/2021/", False),
        ("https://www.example.com/product/123/", False),
        ("https://www.example.com/about/team/", False),
    ])
    def test_pagination(self, url_processor, url, expected):
        assert url_processor.is_pagination_url(url) == expected


class TestIsCategoryOrTagUrl:
    """WordPress category/tag URL detection."""

    @pytest.mark.parametrize("url, expected", [
        # Category patterns
        ("https://www.example.com/category/garden/", True),
        ("https://www.example.com/categories/plants/", True),
        ("https://www.example.com/cat/herbs/", True),
        ("https://www.example.com/topics/cooking/", True),
        ("https://www.example.com/subject/science/", True),
        ("https://www.example.com/page?cat=5", True),
        ("https://www.example.com/page?category=garden", True),
        ("https://www.example.com/page?category_name=garden", True),
        # Tag patterns
        ("https://www.example.com/tag/summer/", True),
        ("https://www.example.com/tags/featured/", True),
        ("https://www.example.com/label/hot/", True),
        ("https://www.example.com/keyword/organic/", True),
        ("https://www.example.com/topic/diy/", True),
        ("https://www.example.com/page?tag=featured", True),
        # NOT category/tag
        ("https://www.example.com/about", False),
        ("https://www.example.com/news/article", False),
        ("https://www.example.com/", False),
    ])
    def test_category_tag(self, url_processor, url, expected):
        assert url_processor.is_category_or_tag_url(url) == expected


class TestFilterUrls:
    """filter_urls combines normalization, validation, and optional filtering."""

    def test_basic_filtering(self, url_processor):
        urls = [
            "https://www.example.com/About/",
            "https://www.EXAMPLE.COM/about",
            "https://www.EXAMPLE.COM/about/",  # duplicate of above after normalization
            "https://www.example.com/style.css",
        ]
        result = url_processor.filter_urls(urls)
        # /About and /about both normalize to the same lowercase path
        assert "https://www.example.com/about" in result
        assert len(result) == 1  # one unique URL (.css filtered, two /about variants deduped)

    def test_pagination_filter(self, pagination_config):
        from sitemap_comparison import UrlProcessor
        proc = UrlProcessor(pagination_config)
        urls = [
            "https://www.example.com/news/page/2/",
            "https://www.example.com/news/article",
        ]
        result = proc.filter_urls(urls)
        assert "https://www.example.com/news/article" in result
        assert "https://www.example.com/news/page/2" not in result

    def test_categories_tags_filter(self, categories_tags_config):
        from sitemap_comparison import UrlProcessor
        proc = UrlProcessor(categories_tags_config)
        urls = [
            "https://www.example.com/category/garden/",
            "https://www.example.com/tag/summer/",
            "https://www.example.com/about",
        ]
        result = proc.filter_urls(urls)
        assert "https://www.example.com/about" in result
        assert len(result) == 1  # only /about survives

    def test_empty_input(self, url_processor):
        assert url_processor.filter_urls(set()) == set()
        assert url_processor.filter_urls([]) == set()

    def test_all_invalid(self, url_processor):
        urls = [
            "https://www.example.com/a.pdf",
            "https://www.example.com/b.zip",
            "https://www.example.com/c.jpg",
        ]
        assert url_processor.filter_urls(urls) == set()
