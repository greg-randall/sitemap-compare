# Sitemap Comparison Tool

A powerful Python utility that compares URLs found in a website's sitemap with URLs discovered by crawling the site. This tool helps identify discrepancies between what search engines see in your sitemap and what's actually accessible on your website.

## Why Use This Tool?

Sitemaps are crucial for SEO as they guide search engines to your content. However, discrepancies between your sitemap and actual site structure can lead to:

- **Wasted crawl budget**: Search engines waste resources on non-existent pages
- **Missed content**: Important pages might not be indexed if they're missing from your sitemap
- **SEO penalties**: Excessive 404 errors from invalid sitemap URLs can negatively impact rankings

This tool helps you identify and fix these issues by:
- Finding URLs in your sitemap that aren't accessible when crawling the site
- Discovering pages on your site that aren't included in your sitemap
- Caching problematic pages for further investigation

## Features

- Automatic sitemap discovery (checks robots.txt and common locations)
- Handles sitemap indexes and nested sitemaps
- Multi-threaded crawling for efficient site exploration
- Robust URL normalization to avoid false positives
- Graceful handling of connection issues with exponential backoff
- Caching of page content for offline analysis
- Comprehensive logging for troubleshooting
- Handles malformed XML with fallback parsing methods

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/sitemap-comparison.git
   cd sitemap-comparison
   ```

2. Install dependencies:
   ```
   pip install curl-cffi beautifulsoup4
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
                            [--workers WORKERS] [--max-pages MAX_PAGES] start_url
```

- `start_url`: The URL to start crawling from (required)
- `--sitemap-url`: The URL of the sitemap (optional, will try to discover if not provided)
- `--output-prefix`: Prefix for output files (default: 'comparison_results')
- `--workers`: Number of parallel workers for crawling (default: 4)
- `--max-pages`: Maximum number of pages to crawl (default: 10000)

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

3. **Comparison**:
   - Identifies URLs present in the sitemap but not found during crawling
   - Finds URLs discovered during crawling but missing from the sitemap
   - Caches content for further analysis

## Output

The tool creates a directory structure under `sites/[domain]/[timestamp]/` containing:

- `missing_from_sitemap.txt`: URLs found while crawling but not in the sitemap
- `missing_from_site.txt`: URLs in the sitemap that weren't found while crawling
- `all_sitemap_urls.txt`: All URLs extracted from the sitemap
- `all_site_urls.txt`: All URLs discovered while crawling
- `cache/`: Directory containing cached HTML content from crawled pages
- `cache-xml/`: Directory containing cached sitemap XML files

## Troubleshooting

- **Sitemap Discovery Fails**: Use the `--sitemap-url` parameter to specify the sitemap location directly
- **Crawling Too Slow**: Increase the number of workers with `--workers`
- **Too Many Pages**: Limit the crawl with `--max-pages`
- **Memory Issues**: Reduce the number of workers and max pages
- **Connection Errors**: The tool implements exponential backoff, but you might need to run it again if a site has strict rate limiting

## License

[MIT License](LICENSE)
