"""Tests for Config — argument parsing and attribute defaults."""
import argparse
import pytest
from sitemap_comparison import Config


class TestConfigDefaults:
    """Verify Config attribute extraction from argparse.Namespace."""

    def test_basic_defaults(self):
        args = argparse.Namespace(
            start_url="https://www.example.com",
            sitemap_url=None,
            output_prefix="results",
            workers=8,
            max_pages=500,
            verbose=True,
            compare_previous=False,
            ignore_pagination=True,
            ignore_categories_tags=True,
            thread_timeout=60,
            obscura_path="/usr/local/bin/obscura",
            obscura_wait=5,
            obscura_wait_until="networkidle",
            obscura_timeout=45,
            obscura_stealth_disable=True,
            curl_cffi=True,
        )
        config = Config(args)
        assert config.start_url == "https://www.example.com"
        assert config.sitemap_url is None
        assert config.workers == 8
        assert config.max_pages == 500
        assert config.verbose is True
        assert config.compare_previous is False
        assert config.ignore_pagination is True
        assert config.ignore_categories_tags is True
        assert config.thread_timeout == 60
        assert config.obscura_path == "/usr/local/bin/obscura"
        assert config.obscura_wait == 5
        assert config.obscura_wait_until == "networkidle"
        assert config.obscura_timeout == 45
        assert config.obscura_stealth is False   # stealth_disable=True flips it
        assert config.curl_cffi is True

    def test_stealth_default(self):
        """Stealth is ON by default (--obscura-stealth-disable not passed)."""
        args = argparse.Namespace(
            start_url="https://www.example.com",
            sitemap_url=None, output_prefix="", workers=4, max_pages=100,
            verbose=False, compare_previous=False, ignore_pagination=False,
            ignore_categories_tags=False, thread_timeout=30,
            obscura_path="obscura", obscura_wait=1, obscura_wait_until="load",
            obscura_timeout=None, curl_cffi=False,
        )
        config = Config(args)
        # stealth_disable attribute missing → default False → stealth is True
        assert config.obscura_stealth is True

    def test_stealth_disabled(self):
        """--obscura-stealth-disable sets stealth to False."""
        args = argparse.Namespace(
            start_url="https://www.example.com",
            sitemap_url=None, output_prefix="", workers=4, max_pages=100,
            verbose=False, compare_previous=False, ignore_pagination=False,
            ignore_categories_tags=False, thread_timeout=30,
            obscura_path="obscura", obscura_wait=1, obscura_wait_until="load",
            obscura_timeout=None, obscura_stealth_disable=True, curl_cffi=False,
        )
        config = Config(args)
        assert config.obscura_stealth is False

    def test_obscura_timeout_falls_back_to_thread_timeout(self):
        """When obscura_timeout is None, it inherits thread_timeout."""
        args = argparse.Namespace(
            start_url="https://www.example.com",
            sitemap_url=None, output_prefix="", workers=4, max_pages=100,
            verbose=False, compare_previous=False, ignore_pagination=False,
            ignore_categories_tags=False, thread_timeout=42,
            obscura_path="obscura", obscura_wait=1, obscura_wait_until="load",
            obscura_timeout=None, obscura_stealth_disable=False, curl_cffi=False,
        )
        config = Config(args)
        assert config.obscura_timeout == 42

    def test_domain_parsing(self):
        """Domain is extracted from start_url."""
        args = argparse.Namespace(
            start_url="https://www.api.org/some/path",
            sitemap_url=None, output_prefix="", workers=4, max_pages=100,
            verbose=False, compare_previous=False, ignore_pagination=False,
            ignore_categories_tags=False, thread_timeout=30,
            obscura_path="obscura", obscura_wait=1, obscura_wait_until="load",
            obscura_timeout=None, obscura_stealth_disable=False, curl_cffi=False,
        )
        config = Config(args)
        assert config.domain == "www.api.org"

    def test_output_dir_structure(self):
        """output_dir is sites/<domain>/<timestamp>."""
        args = argparse.Namespace(
            start_url="https://blog.example.com/",
            sitemap_url=None, output_prefix="", workers=4, max_pages=100,
            verbose=False, compare_previous=False, ignore_pagination=False,
            ignore_categories_tags=False, thread_timeout=30,
            obscura_path="obscura", obscura_wait=1, obscura_wait_until="load",
            obscura_timeout=None, obscura_stealth_disable=False, curl_cffi=False,
        )
        config = Config(args)
        assert config.output_dir.startswith("sites/blog.example.com/")

    def test_curl_cffi_flag(self):
        """--curl-cffi enables the fallback mode."""
        args = argparse.Namespace(
            start_url="https://www.example.com",
            sitemap_url=None, output_prefix="", workers=4, max_pages=100,
            verbose=False, compare_previous=False, ignore_pagination=False,
            ignore_categories_tags=False, thread_timeout=30,
            obscura_path="obscura", obscura_wait=1, obscura_wait_until="load",
            obscura_timeout=None, obscura_stealth_disable=False, curl_cffi=True,
        )
        config = Config(args)
        assert config.curl_cffi is True
