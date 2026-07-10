"""Tests for CacheManager — URL-to-filename conversion and file caching."""
import os
import pytest
from sitemap_comparison import CacheManager


class TestUrlToFilename:
    """URLs are converted to safe filenames, truncated at 200 chars."""

    def test_simple_url(self, sample_config):
        cm = CacheManager(sample_config)
        result = cm.url_to_filename("https://www.example.com/about")
        assert "www.example.com" in result
        assert "about" in result
        # URL-encoded: slashes become %2F, colons become %3A
        assert result.startswith("https%3A")

    def test_special_characters(self, sample_config):
        cm = CacheManager(sample_config)
        result = cm.url_to_filename("https://www.example.com/page?id=123&ref=nav")
        # Query chars are percent-encoded
        assert "%3F" in result or "?" not in result  # ? encoded

    def test_long_url_truncation(self, sample_config):
        cm = CacheManager(sample_config)
        long_url = "https://www.example.com/" + "a" * 500
        result = cm.url_to_filename(long_url)
        assert len(result) <= 200


class TestCacheContent:
    """Content is written to disk with correct directory and extension."""

    def test_html_cache(self, sample_config, tmp_path):
        sample_config.output_dir = str(tmp_path)
        cm = CacheManager(sample_config)
        cm.cache_content("https://www.example.com/about", "<html>about</html>", is_sitemap=False)
        # Should be in cache/ directory with .html extension
        cache_dir = os.path.join(str(tmp_path), "cache")
        assert os.path.isdir(cache_dir)
        files = os.listdir(cache_dir)
        assert len(files) == 1
        assert files[0].endswith(".html")

    def test_sitemap_cache(self, sample_config, tmp_path):
        sample_config.output_dir = str(tmp_path)
        cm = CacheManager(sample_config)
        cm.cache_content("https://www.example.com/sitemap.xml", "<urlset>...</urlset>", is_sitemap=True)
        # Should be in cache-xml/ with .xml extension
        cache_dir = os.path.join(str(tmp_path), "cache-xml")
        assert os.path.isdir(cache_dir)
        files = os.listdir(cache_dir)
        assert len(files) == 1
        assert files[0].endswith(".xml")

    def test_content_matches(self, sample_config, tmp_path):
        sample_config.output_dir = str(tmp_path)
        cm = CacheManager(sample_config)
        content = "<html><body>test page</body></html>"
        cm.cache_content("https://www.example.com/page", content, is_sitemap=False)

        cache_dir = os.path.join(str(tmp_path), "cache")
        filepath = os.path.join(cache_dir, os.listdir(cache_dir)[0])
        with open(filepath, "r", encoding="utf-8") as f:
            assert f.read() == content

    def test_no_output_dir(self, sample_config):
        sample_config.output_dir = None
        cm = CacheManager(sample_config)
        # Should not raise
        cm.cache_content("https://www.example.com/page", "content", is_sitemap=False)


class TestCopyOutputFiles:
    """copy_output_files copies CSV files from output dir to results/."""

    def test_copies_files(self, sample_config, tmp_path):
        sample_config.output_dir = str(tmp_path)
        cm = CacheManager(sample_config)
        # Create a fake CSV file
        csv_content = "Source,URL\nhttps://example.com,https://example.com/page\n"
        with open(os.path.join(str(tmp_path), "all_site_urls.csv"), "w") as f:
            f.write(csv_content)

        cm.copy_output_files()
        results_dir = os.path.join(str(tmp_path), "results")
        assert os.path.isdir(results_dir)
        assert os.path.exists(os.path.join(results_dir, "all_site_urls.csv"))

    def test_no_files(self, sample_config, tmp_path):
        sample_config.output_dir = str(tmp_path)
        cm = CacheManager(sample_config)
        # No CSV files exist — should not crash
        result = cm.copy_output_files()
        assert result is False
