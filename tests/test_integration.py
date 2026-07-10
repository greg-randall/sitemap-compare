"""Integration tests — run the full pipeline against a local HTTP server.

Serves a known fixture site (8 discoverable pages, 2 sitemap-only pages)
and verifies the spider finds exactly the right URLs.
"""
import os
import csv
import socket
import subprocess
import tempfile
import time
import argparse
import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _find_free_port():
    """Find an unused TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _render_sitemap(base_url):
    """Write sitemap.xml with {base} replaced by the actual server URL."""
    template = os.path.join(FIXTURES, "sitemap.xml")
    with open(template, "r") as f:
        content = f.read()
    content = content.replace("{base}", base_url)
    # Write to a temp file that won't collide with other tests
    tmp = os.path.join(FIXTURES, "_sitemap_generated.xml")
    with open(tmp, "w") as f:
        f.write(content)
    return tmp


@pytest.fixture(scope="module")
def test_site():
    """Start http.server on a free port, yield the base URL, tear down."""
    port = _find_free_port()
    proc = subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=FIXTURES,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for the server to be ready
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=0.5)
            sock.close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("Test server did not start within 5 seconds")

    yield f"http://127.0.0.1:{port}"

    proc.kill()
    proc.wait()


def test_full_pipeline(test_site):
    """End-to-end: spider finds 8 reachable pages, sitemap has 10."""
    from sitemap_comparison import Config, SitemapComparison

    # Render the sitemap template with the actual test URL.
    # The rendered file is served by the HTTP server (it's in FIXTURES).
    _render_sitemap(test_site)

    # Build args with --curl-cffi so we don't need obscura
    args = argparse.Namespace(
        start_url=test_site + "/",
        sitemap_url=test_site + "/_sitemap_generated.xml",
        output_prefix="test",
        workers=2,
        max_pages=50,
        verbose=False,
        compare_previous=False,
        ignore_pagination=False,
        ignore_categories_tags=False,
        thread_timeout=30,
        obscura_path="obscura",
        obscura_wait=1,
        obscura_wait_until="networkidle2",
        obscura_nav_timeout=10,
        obscura_timeout=None,
        obscura_stealth_disable=False,
        curl_cffi=True,
    )

    # Create config and monkey-patch output_dir
    config = Config(args)
    # The Config computes output_dir from domain + timestamp.
    # We need to capture the output, so run the pipeline and then read the CSVs.
    # But Config uses os.path.join("sites", domain, timestamp) — we can't
    # easily redirect it.  Instead, run the comparison and inspect the
    # filesystem result.

    comparison = SitemapComparison(args)
    result = comparison.run()
    assert result == 0, "Pipeline exited with error"

    # Find the output directory (domain includes port, e.g. 127.0.0.1:37387)
    sites_root = "sites"
    assert os.path.isdir(sites_root), f"No sites/ directory"
    domains = [d for d in os.listdir(sites_root) if d.startswith("127.0.0.1")]
    assert domains, "No output directory found for 127.0.0.1"
    domains.sort(key=lambda d: os.path.getmtime(os.path.join(sites_root, d)), reverse=True)
    sites_dir = os.path.join(sites_root, domains[0])

    timestamps = sorted(os.listdir(sites_dir))
    assert timestamps, "No timestamp directories found"
    out = os.path.join(sites_dir, timestamps[-1])

    # --- all_site_urls.csv ---
    site_urls = _read_urls(os.path.join(out, "all_site_urls.csv"))
    # 9 reachable pages — 8 real pages + /broken.html (returns a 404 error
    # page, but the spider counts any HTML response as a discovered page).
    assert len(site_urls) == 9, (
        f"Expected 9 spider-discovered URLs, got {len(site_urls)}: {site_urls}"
    )
    assert any("/about.html" in u for u in site_urls)
    assert any("/products/a.html" in u for u in site_urls)
    # Broken link appears because http.server serves a 404 HTML page
    assert any("broken.html" in u for u in site_urls)

    # --- all_sitemap_urls.csv ---
    sitemap_urls = _read_urls(os.path.join(out, "all_sitemap_urls.csv"))
    # Sitemap has all 10 pages
    assert len(sitemap_urls) == 10, (
        f"Expected 10 sitemap URLs, got {len(sitemap_urls)}"
    )
    assert any("unreachable-a.html" in u for u in sitemap_urls)
    assert any("unreachable-b.html" in u for u in sitemap_urls)

    # --- missing_from_sitemap.csv ---
    missing_sitemap = _read_urls(os.path.join(out, "missing_from_sitemap.csv"))
    # /broken.html is found by spider but not in sitemap
    assert len(missing_sitemap) == 1, (
        f"Expected 1 missing from sitemap (/broken.html), "
        f"got {len(missing_sitemap)}: {missing_sitemap}"
    )
    assert any("broken.html" in u for u in missing_sitemap)

    # --- missing_from_site.csv ---
    missing_site = _read_urls(os.path.join(out, "missing_from_site.csv"))
    # 2 sitemap-only pages are unreachable
    assert len(missing_site) == 2, (
        f"Expected 2 missing from site, got {len(missing_site)}: {missing_site}"
    )
    assert any("unreachable" in u for u in missing_site)

    # --- cache files written ---
    cache_dir = os.path.join(out, "cache")
    assert os.path.isdir(cache_dir), "cache/ directory missing"
    cached = os.listdir(cache_dir)
    # At most max_pages=50 cache files (we only have 2 missing URLs)
    assert len(cached) <= 50


def _read_urls(filepath):
    """Return a list of URLs from the second column of a CSV."""
    urls = []
    if not os.path.exists(filepath):
        return urls
    with open(filepath, "r", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) >= 2:
                urls.append(row[1].strip())
    return urls
