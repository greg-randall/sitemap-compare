# Sitemap Comparison Tool

## 1. What it is and why

Most websites publish a sitemap, an XML file that tells search engines which pages exist. Sitemaps lie. They list pages that aren't reachable by following links, and they miss pages a visitor would actually find. These gaps matter. An unreachable page in your sitemap wastes crawl budget and frustrates users who land on 404s. A reachable page missing from your sitemap is invisible to search engines.

This tool finds both kinds of gaps. It reads your sitemap, crawls your site by following every link it can find (including links injected by JavaScript), then compares the two lists. The result is a pair of CSVs: pages in your sitemap that nobody can reach, and pages anyone can reach that your sitemap forgot. It also generates an interactive HTML report, caches every page it fetches for offline analysis, and compares scans over time so you can see whether things are getting better or worse.

Run it on your own site to audit your SEO coverage. Run it on a competitor's site to map what they've published but haven't linked to. Run it on a site you're about to redesign so you know what's really there.

## 2. Quickstart

```bash
# Clone and install Python dependencies
git clone https://github.com/greg-randall/sitemap-compare
cd sitemap-compare
pip install -r requirements.txt

# Install obscura (JS-rendering headless browser)
# Linux x86_64. See https://github.com/h4ckf0r0day/obscura/releases for other platforms
curl -LO https://github.com/h4ckf0r0day/obscura/releases/latest/download/obscura-x86_64-linux.tar.gz
tar xzf obscura-x86_64-linux.tar.gz
sudo mv obscura obscura-worker /usr/local/bin/

# Run the tool
python sitemap_comparison.py https://example.com

# Generate an HTML report from the results
python sitemap_report.py
```

You should see output like:

```
Discovering sitemap for https://example.com...
Found sitemap in robots.txt: https://example.com/sitemap.xml
Extracting URLs from sitemap...
Found 142 valid URLs in sitemap
Spidering website: https://example.com
Spidering complete. Found 118 URLs
Found 31 URLs missing from sitemap
Found 55 URLs missing from site
Caching 55 missing URLs...
Comparison complete!
Results saved to: sites/example.com/07-10-2026_10-45pm
```

Your results land in `sites/example.com/07-10-2026_10-45pm/`. The HTML report is at `reports/index.html`.

If obscura isn't available, fall back to static HTTP requests (no JavaScript rendering):

```bash
python sitemap_comparison.py https://example.com --curl-cffi
```

## 3. How it works

The tool does three things in sequence, then optionally compares against history.

**First, it finds your sitemap.** It checks `/robots.txt` for a `Sitemap:` directive. If that fails, it probes about 40 common sitemap locations (`/sitemap.xml`, `/wp-sitemap.xml`, `/sitemap_index.xml`, and so on). Once found, it downloads the sitemap and extracts every URL inside `<loc>` tags. If the sitemap is an index (pointing to other sitemaps), it follows those too, recursively, with a guard against self-referential loops. It handles malformed XML, HTML sitemaps, and plain-text URL lists as fallbacks.

**Second, it crawls your site.** Starting from the homepage, it visits each page, extracts every `<a href>` link, and adds new URLs to a queue. It stays within the same domain, strips out binary files (images, PDFs, fonts), removes tracking parameters (`utm_source`, `fbclid`, `gclid`, and hundreds more) so it doesn't crawl the same page twice with different junk in the URL, and normalizes fragments. The crawl runs with four parallel workers by default, using obscura, a headless browser with a real V8 JavaScript engine, so links injected by client-side JS are discovered. If a worker stalls, a watchdog timer fires and the crawl shuts down gracefully rather than hanging. Pages that fail to load get three retries with a short backoff.

**Third, it compares the two lists.** Sitemap URLs are normalized (domain lowercased, trailing slashes and query strings stripped) and compared against the normalized crawl URLs. The difference produces two CSVs: *missing from sitemap* (pages found by crawling but absent from the sitemap) and *missing from site* (pages the sitemap declares but the crawler couldn't reach). The tool then fetches and caches every URL in the second category. These are the interesting ones: pages that exist on the server but aren't linked from anywhere a visitor would find.

**Optionally**, if a previous scan of the same domain exists, it runs a historical comparison, flagging which issues are new and which have been fixed since last time.

**Finally**, running `sitemap_report.py` reads all scans in the `sites/` directory and builds an interactive HTML dashboard with searchable tables and trend charts.

## 4. Technical detail

### Architecture

```
sitemap_comparison.py          # Main engine: crawl, compare, cache
sitemap_report.py              # HTML report generator (run separately)
tests/                         # pytest suite (132 tests, 8 modules)
sites/<domain>/<timestamp>/    # Per-scan output directory
reports/                       # Generated HTML reports
```

### Key classes (sitemap_comparison.py)

| Class | Responsibility |
|-------|---------------|
| `Config` | Parses CLI args, computes derived values (domain, output path, timestamp) |
| `UrlProcessor` | Normalizes URLs (lowercase domain, strip trailing slash / query params / fragments), validates URLs (skip binary extensions, tracking query params), detects pagination and WordPress category/tag URLs for filtering |
| `CacheManager` | Writes fetched content to disk under `cache/` (HTML) or `cache-xml/` (sitemaps), copies output CSVs to `results/` |
| `ThreadMonitor` | Daemon thread that watches worker threads; fires an `on_timeout` callback (which interrupts the spider) if any thread exceeds the time limit |
| `SitemapFetcher` | Discovers sitemaps via robots.txt and common-location probing, extracts URLs from sitemap XML using regex → ElementTree → BeautifulSoup → plain-text fallbacks, recursively processes sitemap indexes with a visited-set guard against infinite loops |
| `WebsiteSpider` | Multi-threaded crawl: workers pull URLs from a queue, fetch via obscura (or curl_cffi if `--curl-cffi`), parse with BeautifulSoup, enqueue discovered links. Handles retry, thread monitoring, and graceful shutdown on interrupt |
| `ReportGenerator` | Writes CSV reports (sitemap vs site diff, all URLs), generates historical comparison CSVs |
| `ComparisonAnalyzer` | Finds the most recent previous scan for a domain, diffs current vs previous CSV files to produce new/fixed counts |
| `SitemapComparison` | Orchestrator: wires up all components, runs the full pipeline (sitemap → crawl → compare → cache → historical comparison) |

### External dependencies

| Dependency | Role |
|-----------|------|
| **obscura** (Rust binary, v0.1.9+) | Headless browser with V8 for JavaScript rendering during crawl. Default engine. Installed separately from GitHub releases. |
| **curl_cffi** (Python, `>=0.5.7`) | TLS-impersonated HTTP client. Used for sitemap/robots.txt fetching (no JS needed). Also available as a crawl fallback via `--curl-cffi`. |
| **courlan** (Python, `>=1.0.0`) | Strips tracking query parameters using the ClearURLs rule set (400+ patterns) before URL dedup. |
| **beautifulsoup4** (Python, `>=4.12.0`) | HTML parsing for link extraction and sitemap fallback parsing. |
| **tqdm** (Python, `>=4.65.0`) | Progress bars for non-verbose mode. |
| **pytz** (Python, `>=2023.3`) | Timezone handling for timestamps. |

### Output directory structure

```
sites/<domain>/<timestamp>/
  all_sitemap_urls.csv          # Every URL extracted from the sitemap
  all_site_urls.csv             # Every URL discovered by crawling
  missing_from_sitemap.csv      # Crawl-found URLs absent from sitemap
  missing_from_site.csv         # Sitemap URLs unreachable by crawling
  comparison_missing_from_site.csv     # (if --compare-previous) new/fixed
  comparison_missing_from_sitemap.csv # (if --compare-previous) new/fixed
  cache/                        # Cached HTML from crawled pages
  cache-xml/                    # Cached sitemap XML files
  results/                      # Copies of the CSVs for easy access
```

### Full CLI reference

```
python sitemap_comparison.py <start_url> [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `start_url` | *(required)* | URL to start crawling from |
| `--sitemap-url` | auto-discover | Explicit sitemap URL (bypasses discovery) |
| `--workers` | 4 | Number of parallel crawl workers |
| `--max-pages` | 10000 | Maximum pages to crawl before stopping |
| `--verbose` | off | Enable verbose logging |
| `--compare-previous` | on | Compare with the most recent previous scan |
| `--no-compare-previous` | - | Skip historical comparison |
| `--ignore-pagination` | off | Filter out pagination URLs from results |
| `--ignore-categories-tags` | off | Filter out WordPress category/tag URLs |
| `--thread-timeout` | 30 | Seconds before a stuck worker triggers shutdown |
| `--obscura-path` | `obscura` | Path to the obscura binary |
| `--obscura-wait` | 1 | Extra seconds to wait after page load for JS |
| `--obscura-wait-until` | `load` | Page load trigger: `load`, `domcontentloaded`, or `networkidle` |
| `--obscura-timeout` | = thread-timeout | Subprocess timeout per obscura call |
| `--obscura-stealth-disable` | off | Disable stealth mode (stealth is on by default) |
| `--curl-cffi` | off | Use curl_cffi for all fetching (no JS rendering) |

### HTML report

```bash
python sitemap_report.py [--open-browser] [--output-dir reports] [--verbose]
```

Scans all domains under `sites/`, generates per-domain index pages and per-scan detail pages with searchable tables and historical trend data. Skips incomplete scans (missing CSV files).

### Running the tests

```bash
pip install pytest pytest-mock
python -m pytest tests/ -v
```

132 tests across 8 modules. No network access required. All HTTP and subprocess calls are mocked.

### Extending

- **Add a new URL filter**: Extend `UrlProcessor.is_valid_url()` or add a new `is_*_url()` method, then wire it into `filter_urls()` and add a CLI flag.
- **Swap the rendering engine**: Implement a `render(url, ...)` function that returns an `ObscuraResponse`-like object, then update the config to select engines. The spider only depends on `.text` and `.headers`.
- **Add a new output format**: Extend `ReportGenerator` with a new `write_*_report()` method and call it from `SitemapComparison.run()`.
- **Change the crawl strategy**: `WebsiteSpider.spider_website()` owns the queue and worker loop. Replace the BFS queue with a priority queue, add depth limits, or swap the concurrency model.

## License

[GNU LGPL 2.1](LICENSE)
