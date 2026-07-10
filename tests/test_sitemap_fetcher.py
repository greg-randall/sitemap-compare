"""Tests for SitemapFetcher — URL extraction from sitemap XML and HTML."""
import pytest
from sitemap_comparison import SitemapFetcher, CacheManager


SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://www.example.com/page1</loc>
    </url>
    <url>
        <loc>https://www.example.com/page2</loc>
    </url>
</urlset>"""

SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap>
        <loc>https://www.example.com/sitemap-posts.xml</loc>
    </sitemap>
    <sitemap>
        <loc>https://www.example.com/sitemap-pages.xml</loc>
    </sitemap>
</sitemapindex>"""

MALFORMED_XML = """<html><body>
<loc>https://www.example.com/bad-xml-page</loc>
<a href="https://www.example.com/linked-page">link</a>
</body></html>"""

SELF_REFERENTIAL_XML = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap>
        <loc>https://www.example.com/sitemap.xml</loc>
    </sitemap>
</sitemapindex>"""


@pytest.fixture
def sitemap_fetcher(sample_config):
    cm = CacheManager(sample_config)
    from sitemap_comparison import UrlProcessor
    up = UrlProcessor(sample_config)
    return SitemapFetcher(sample_config, cm, up)


class TestExtractUrlsWithRegex:
    """Regex-based URL extraction from sitemap content."""

    def test_loc_tags(self, sitemap_fetcher):
        urls = sitemap_fetcher.extract_urls_with_regex(SITEMAP_XML, "https://www.example.com/sitemap.xml")
        assert "https://www.example.com/page1" in urls
        assert "https://www.example.com/page2" in urls
        assert len(urls) == 2

    def test_malformed_xml(self, sitemap_fetcher):
        urls = sitemap_fetcher.extract_urls_with_regex(MALFORMED_XML, "https://www.example.com/")
        assert "https://www.example.com/bad-xml-page" in urls

    def test_empty_content(self, sitemap_fetcher):
        urls = sitemap_fetcher.extract_urls_with_regex("", "https://www.example.com/")
        assert len(urls) == 0


class TestGetSitemapUrls:
    """Full sitemap URL extraction with mocked HTTP."""

    def test_simple_sitemap(self, sitemap_fetcher, mocker):
        mock_get = mocker.patch("sitemap_comparison.requests.get")
        mock_get.return_value = mocker.Mock(
            text=SITEMAP_XML,
            status_code=200,
        )
        mock_get.return_value.raise_for_status = mocker.Mock()

        urls, sources = sitemap_fetcher.get_sitemap_urls("https://www.example.com/sitemap.xml")
        assert "https://www.example.com/page1" in urls
        assert "https://www.example.com/page2" in urls
        assert len(urls) == 2

    def test_sitemap_index_recursion(self, sitemap_fetcher, mocker):
        """Sitemap index triggers recursive fetch of sub-sitemaps."""
        mock_get = mocker.patch("sitemap_comparison.requests.get")
        # First call: sitemap index, second: sub-sitemap
        mock_get.side_effect = [
            mocker.Mock(text=SITEMAP_INDEX_XML, status_code=200,
                        raise_for_status=mocker.Mock()),
            mocker.Mock(text=SITEMAP_XML, status_code=200,
                        raise_for_status=mocker.Mock()),
            mocker.Mock(text=SITEMAP_XML, status_code=200,
                        raise_for_status=mocker.Mock()),
        ]

        urls, sources = sitemap_fetcher.get_sitemap_urls("https://www.example.com/sitemap-index.xml")
        # 2 sub-sitemaps × 2 URLs each = 4 unique URLs
        assert len(urls) == 2  # SITEMAP_XML has 2 unique URLs

    def test_visited_guard_prevents_recursion(self, sitemap_fetcher, mocker):
        """Self-referential sitemaps are visited only once."""
        mock_get = mocker.patch("sitemap_comparison.requests.get")
        mock_get.return_value = mocker.Mock(
            text=SELF_REFERENTIAL_XML,
            status_code=200,
            raise_for_status=mocker.Mock(),
        )

        urls, sources = sitemap_fetcher.get_sitemap_urls("https://www.example.com/sitemap.xml")
        # Should not recurse infinitely — the visited guard stops it
        assert mock_get.call_count == 1

    def test_http_error_falls_through_to_regex(self, sitemap_fetcher, mocker):
        """When HTTP request fails, regex extraction is tried on any partial content."""
        mock_get = mocker.patch("sitemap_comparison.requests.get")
        mock_get.side_effect = Exception("Connection refused")

        urls, sources = sitemap_fetcher.get_sitemap_urls("https://www.example.com/sitemap.xml")
        # Should return empty sets, not crash
        assert urls == set()
        assert sources == {}

    def test_sub_sitemap_detection_xml_extension(self, sitemap_fetcher):
        """Only .xml/.xml.gz files or known sitemap paths are treated as sub-sitemaps."""
        content = """<loc>https://www.example.com/not-a-sitemap</loc>
<loc>https://www.example.com/actual-sitemap.xml</loc>
<loc>https://www.example.com/sitemap/posts</loc>"""
        urls = sitemap_fetcher.extract_urls_with_regex(content, "https://www.example.com/")
        assert "https://www.example.com/not-a-sitemap" in urls
        assert "https://www.example.com/actual-sitemap.xml" in urls
