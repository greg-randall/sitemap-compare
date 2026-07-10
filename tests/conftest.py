"""Shared fixtures and path setup for sitemap comparison tests."""
import sys
import os
import argparse
import pytest

# Add project root to path so tests can import sitemap_comparison
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_args():
    """Minimal argparse.Namespace with defaults matching the CLI."""
    return argparse.Namespace(
        start_url="https://www.example.com",
        sitemap_url=None,
        output_prefix="comparison_results",
        workers=4,
        max_pages=10000,
        verbose=False,
        compare_previous=True,
        ignore_pagination=False,
        ignore_categories_tags=False,
        thread_timeout=30,
        obscura_path="obscura",
        obscura_wait=1,
        obscura_wait_until="networkidle2",
        obscura_nav_timeout=10,
        obscura_timeout=None,
        obscura_stealth_disable=False,
        curl_cffi=False,
    )


@pytest.fixture
def sample_config(sample_args):
    """Config object built from sample_args."""
    from sitemap_comparison import Config
    return Config(sample_args)


@pytest.fixture
def url_processor():
    """Fresh UrlProcessor with default config."""
    from sitemap_comparison import Config, UrlProcessor
    args = argparse.Namespace(
        start_url="https://www.example.com",
        sitemap_url=None,
        output_prefix="comparison_results",
        workers=4,
        max_pages=10000,
        verbose=False,
        compare_previous=True,
        ignore_pagination=False,
        ignore_categories_tags=False,
        thread_timeout=30,
        obscura_path="obscura",
        obscura_wait=1,
        obscura_wait_until="networkidle2",
        obscura_nav_timeout=10,
        obscura_timeout=None,
        obscura_stealth_disable=False,
        curl_cffi=False,
    )
    config = Config(args)
    return UrlProcessor(config)


@pytest.fixture
def pagination_config(sample_args):
    """Config with pagination filtering enabled."""
    sample_args.ignore_pagination = True
    from sitemap_comparison import Config
    return Config(sample_args)


@pytest.fixture
def categories_tags_config(sample_args):
    """Config with category/tag filtering enabled."""
    sample_args.ignore_categories_tags = True
    from sitemap_comparison import Config
    return Config(sample_args)


@pytest.fixture
def sample_urls():
    """Set of test URLs covering edge cases."""
    return [
        "https://www.example.com/",
        "https://www.example.com/about",
        "https://www.example.com/about/",
        "https://www.example.com/news/page/2/",
        "https://www.example.com/product?id=123&utm_source=twitter&fbclid=abc",
        "https://www.EXAMPLE.COM/ABOUT",
        "https://www.example.com/about#section",
        "https://www.example.com/about/team/",
        "https://www.example.com/style.css",
        "https://www.example.com/image.png?w=800",
        "javascript:void(0)",
        "",
    ]
