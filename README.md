# Sitemap Comparison Tool

A Python utility that compares URLs found in a website's sitemap with URLs discovered by crawling the site. This tool helps identify discrepancies between what's publicly disclosed in sitemaps and what's actually accessible on a website.

## Why Use This Tool?

Websites often contain content that isn't explicitly listed in their sitemaps. This can include:

- **Hidden content**: Pages intentionally excluded from sitemaps but still accessible
- **Orphaned pages**: Content that exists but isn't linked from main navigation
- **Restricted areas**: Sections that site owners don't want widely discovered
- **Development artifacts**: Test pages, staging content, or admin interfaces
- **Legacy content**: Outdated pages that weren't properly removed

This tool helps you discover this hidden content by:
- Finding URLs in the sitemap that aren't easily accessible when crawling the site
- Discovering pages on the site that aren't included in the sitemap
- Caching all discovered content for offline analysis
- Revealing the true structure of a website beyond what's officially presented

## Features

- Automatic sitemap discovery (checks robots.txt and common locations)
- Handles sitemap indexes and nested sitemaps
- Multi-threaded crawling for efficient site exploration
- Robust URL normalization to avoid false positives
- Graceful handling of connection issues with exponential backoff
- Caching of page content for offline analysis
- Comprehensive logging for troubleshooting
- Handles malformed XML with fallback parsing methods
- Historical comparison to track changes between scans
- Discovers content not intended for public visibility
- Reveals the "dark corners" of websites that aren't in the sitemap
- Identifies potential security issues through exposed but unlisted pages
- HTML report generation for easy analysis and sharing of results

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/greg-randall/sitemap-compare
   cd sitemap-comparison
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

Basic usage:

```
python sitemap_comparison.py https://example.com
```

The tool will:
1. Attempt to discover the sitemap automatically
2. Extract all URLs from the sitemap
3. Crawl the website to discover accessible URLs
4. Compare the two sets and report differences
5. Cache pages for further analysis

### Command-line Arguments

```
python sitemap_comparison.py [-h] [--sitemap-url SITEMAP_URL] [--output-prefix OUTPUT_PREFIX] 
                            [--workers WORKERS] [--max-pages MAX_PAGES] [--verbose]
                            [--compare-previous] [--ignore-pagination] [--ignore-categories-tags]
                            [--thread-timeout THREAD_TIMEOUT] start_url
```

- `start_url`: The URL to start crawling from (required)
- `--sitemap-url`: The URL of the sitemap (optional, will try to discover if not provided)
- `--output-prefix`: Prefix for output files (default: 'comparison_results')
- `--workers`: Number of parallel workers for crawling (default: 4)
- `--max-pages`: Maximum number of pages to crawl (default: 10000)
- `--verbose`: Enable verbose logging output
- `--compare-previous`: Compare results with the most recent previous scan of the same site (default: True)
- `--ignore-pagination`: Ignore common pagination URLs in the "missing from sitemap" report
- `--ignore-categories-tags`: Ignore WordPress category and tag URLs in the "missing from sitemap" report
- `--thread-timeout`: Maximum time in seconds a thread can spend on a single URL (default: 30)

### Examples

Specify a sitemap URL explicitly:
```
python sitemap_comparison.py https://example.com --sitemap-url https://example.com/sitemap.xml
```

Use more workers for faster crawling:
```
python sitemap_comparison.py https://example.com --workers 8
```

Limit the number of pages to crawl:
```
python sitemap_comparison.py https://example.com --max-pages 1000
```

Compare with previous scan:
```
python sitemap_comparison.py https://example.com --compare-previous
```

Disable comparison with previous scan:
```
python sitemap_comparison.py https://example.com --compare-previous=False
```

Ignore pagination URLs in the missing from sitemap report:
```
python sitemap_comparison.py https://example.com --ignore-pagination
```

Ignore WordPress category and tag URLs in the missing from sitemap report:
```
python sitemap_comparison.py https://example.com --ignore-categories-tags
```


## How It Works

1. **Sitemap Processing**:
   - Discovers or uses the provided sitemap URL
   - Handles sitemap indexes by recursively processing nested sitemaps
   - Extracts all URLs using XML parsing with fallbacks for malformed XML

2. **Website Crawling**:
   - Uses a multi-threaded approach to efficiently discover URLs
   - Follows links while staying within the same domain
   - Normalizes URLs to avoid duplicates due to trivial differences
   - Filters out non-content URLs (images, CSS, etc.)
   - Discovers pages not linked from main navigation
   - Finds content that site owners may not want widely known

3. **Comparison**:
   - Identifies URLs present in the sitemap but not found during crawling
   - Finds URLs discovered during crawling but missing from the sitemap
   - Reveals the "hidden web" of content not meant to be easily discovered
   - Caches all content for offline analysis and investigation

## Output

The tool creates a directory structure under `sites/[domain]/[timestamp]/` containing:

- `missing_from_sitemap.csv`: URLs found while crawling but not in the sitemap (potentially hidden content)
- `missing_from_site.csv`: URLs in the sitemap that weren't found while crawling (possibly restricted content)
- `all_sitemap_urls.csv`: All URLs extracted from the sitemap (what the site owner wants you to see)
- `all_site_urls.csv`: All URLs discovered while crawling (what's actually there)
- `cache/`: Directory containing cached HTML content from crawled pages (for offline analysis)
- `cache-xml/`: Directory containing cached sitemap XML files (for reference)
- `results/`: Directory containing copies of the CSV files for easy access

The most interesting findings are typically in the `missing_from_sitemap.txt` file, which may reveal:
- Admin interfaces
- Development environments
- Internal tools
- Outdated but still accessible content
- Pages intentionally hidden from search engines

## HTML Report Generation

The tool includes a companion script `sitemap_report.py` that generates interactive HTML reports from the comparison results:

```
python sitemap_report.py [--open-browser] [--output-dir DIRECTORY] [--verbose]
```

### Report Generator Arguments

- `--open-browser`: Open the report in a web browser after generation
- `--output-dir`: Output directory for reports (default: 'reports')
- `--verbose`: Enable verbose output for debugging

### Report Features

- **Interactive dashboard** with historical trends
- **Searchable tables** of missing URLs
- **Comparison visualizations** between scans
- **Mobile-friendly design** for viewing on any device
- **Highlights of new issues** since previous scans

After running the sitemap comparison tool on one or more sites, run the report generator to create a comprehensive set of HTML reports that make it easy to analyze the results.

Example:
```
python sitemap_report.py --open-browser
```

This will generate reports in the `reports` directory and automatically open them in your default web browser.

## Troubleshooting

- **Sitemap Discovery Fails**: Use the `--sitemap-url` parameter to specify the sitemap location directly
- **Crawling Too Slow**: Increase the number of workers with `--workers`
- **Connection Errors**: The tool implements exponential backoff, but you might need to run it again if a site has strict rate limiting
- **Access Denied**: Some sites may block automated crawling; consider using a VPN or proxy or creating a pull request using playwright or similar

## License

[MIT License](LICENSE)
