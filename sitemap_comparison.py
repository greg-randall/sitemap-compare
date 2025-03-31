import argparse
import re
import signal
import sys
import concurrent.futures
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET
from curl_cffi import requests
from bs4 import BeautifulSoup
import logging
import html
import queue
import threading
import os
import datetime
import time
import hashlib
from tqdm import tqdm
import csv

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up argument parser
parser = argparse.ArgumentParser(description='Compare sitemap URLs with URLs found by spidering a website')
parser.add_argument('start_url', help='The URL to start spidering from')
parser.add_argument('--sitemap-url', help='The URL of the sitemap (optional, will try to discover if not provided)')
parser.add_argument('--output-prefix', default='comparison_results', help='Prefix for output files')
parser.add_argument('--workers', type=int, default=4, help='Number of parallel workers for spidering (default: 4)')
parser.add_argument('--max-pages', type=int, default=10000, help='Maximum number of pages to spider (default: 10000)')
parser.add_argument('--verbose', action='store_true', help='Enable verbose logging output')
parser.add_argument('--compare-previous', action='store_true', default=True, help='Compare results with the most recent previous scan of the same site (default: True)')
parser.add_argument('--ignore-pagination', action='store_true', help='Ignore common pagination URLs in the "missing from sitemap" report')
parser.add_argument('--ignore-categories-tags', action='store_true', help='Ignore WordPress category and tag URLs in the "missing from sitemap" report')
args = parser.parse_args()

# Set logging level based on verbose flag
if not args.verbose:
    logging.getLogger().setLevel(logging.WARNING)

# Global flag to track interruption
interrupted = False

# Define signal handler for graceful exit
def signal_handler(sig, frame):
    global interrupted
    logging.info("Ctrl+C detected. Shutting down gracefully...")
    interrupted = True

# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)

def discover_sitemap_url(base_url, output_dir=None, verbose=False):
    """Try to automatically discover the sitemap URL."""
    if verbose:
        logging.info(f"Attempting to discover sitemap for {base_url}")
    else:
        print(f"Discovering sitemap for {base_url}...")
    
    # Parse the base URL to get the domain
    parsed_url = urlparse(base_url)
    base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
    
    # Common sitemap locations to check
    potential_locations = [
        f"{base_domain}/sitemap.xml",
        f"{base_domain}/sitemaps.xml",
        f"{base_domain}/sitemap_index.xml",
        f"{base_domain}/sitemap-index.xml",
        f"{base_domain}/sitemaps/sitemap.xml",
        f"{base_domain}/sitemap.html",
        f"{base_domain}/wp-sitemap.xml",
        f"{base_domain}/system/feeds/sitemap",
        f"{base_domain}/page-sitemap.xml",
        f"{base_domain}/post-sitemap.xml",
        f"{base_domain}/sitemap1.xml",
        f"{base_domain}/sitemap2.xml",
        f"{base_domain}/sitemap_1.xml",
        f"{base_domain}/sitemap_2.xml",
        f"{base_domain}/product-sitemap.xml",
        f"{base_domain}/category-sitemap.xml",
        f"{base_domain}/image-sitemap.xml",
        f"{base_domain}/video-sitemap.xml",
        f"{base_domain}/news-sitemap.xml",
        f"{base_domain}/sitemap.gz",
        f"{base_domain}/sitemap.xml.gz",
        f"{base_domain}/sitemap.txt",
        f"{base_domain}/sitemap.json",
        f"{base_domain}/mobile-sitemap.xml",
        f"{base_domain}/sitemap/sitemap.xml",
        f"{base_domain}/sitemap/",
        f"{base_domain}/sitemaps/",
        f"{base_domain}/sitemap.php",
        f"{base_domain}/site-map.xml",
        f"{base_domain}/sitemap/index.xml",
        f"{base_domain}/sitemap/main.xml",
        f"{base_domain}/sitemap/web.xml",
        f"{base_domain}/sitemap/site.xml",
        f"{base_domain}/sitemap-main.xml",
        f"{base_domain}/sitemap/category_0.xml",
        f"{base_domain}/sitemap_products_1.xml",
    ]
    
    # Retry delays for exponential backoff
    retry_delays = [1, 2, 4, 8, 16, 32]
    
    # Check robots.txt first (most reliable method)
    robots_url = f"{base_domain}/robots.txt"
    if verbose:
        logging.info(f"Checking robots.txt at {robots_url}")
    
    for retry, delay in enumerate(retry_delays):
        try:
            response = requests.get(robots_url, timeout=10)
            
            if response.status_code == 200:
                # Look for Sitemap: directive in robots.txt
                for line in response.text.splitlines():
                    if line.lower().startswith('sitemap:'):
                        sitemap_url = line.split(':', 1)[1].strip()
                        if verbose:
                            logging.info(f"Found sitemap in robots.txt: {sitemap_url}")
                        else:
                            print(f"Found sitemap in robots.txt: {sitemap_url}")
                    
                        # Cache the robots.txt file if output_dir is provided
                        if output_dir and response.text:
                            try:
                                robots_cache_file = os.path.join(output_dir, "cache-xml", "robots.txt")
                                with open(robots_cache_file, 'w', encoding='utf-8') as f:
                                    f.write(response.text)
                                if verbose:
                                    logging.debug(f"Cached robots.txt content")
                            except Exception as e:
                                logging.warning(f"Failed to cache robots.txt content: {e}")
                            
                        return sitemap_url
            # If we get here with a 200 status but no sitemap, break the retry loop
            break
        except Exception as e:
            error_message = str(e).lower()
            if any(err in error_message for err in [
                'connection reset', 'connection timed out', 'timeout', 
                'recv failure', 'operation timed out'
            ]):
                if retry < len(retry_delays) - 1:
                    if verbose:
                        logging.warning(f"Connection error checking robots.txt, retrying in {delay}s (attempt {retry+1}/{len(retry_delays)}): {e}")
                    time.sleep(delay)
                    continue
            if verbose:
                logging.warning(f"Error checking robots.txt: {e}")
            break
    
    # Try common locations
    for url in potential_locations:
        if verbose:
            logging.info(f"Checking potential sitemap at {url}")
        
        for retry, delay in enumerate(retry_delays):
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200 and ('<urlset' in response.text or '<sitemapindex' in response.text):
                    if verbose:
                        logging.info(f"Found sitemap at {url}")
                    else:
                        print(f"Found sitemap at {url}")
                    return url
                # If we get here with a 200 status but no valid sitemap, break the retry loop
                break
            except Exception as e:
                error_message = str(e).lower()
                if any(err in error_message for err in [
                    'connection reset', 'connection timed out', 'timeout', 
                    'recv failure', 'operation timed out'
                ]):
                    if retry < len(retry_delays) - 1:
                        if verbose:
                            logging.warning(f"Connection error checking {url}, retrying in {delay}s (attempt {retry+1}/{len(retry_delays)}): {e}")
                        time.sleep(delay)
                        continue
                if verbose:
                    logging.warning(f"Error checking {url}: {e}")
                break
    
    if verbose:
        logging.error("Could not automatically discover sitemap")
    else:
        print("Could not automatically discover sitemap")
    return None

def extract_urls_with_regex(content, base_url):
    """Extract URLs using regex as a fallback method."""
    urls = set()
    
    # First try to extract URLs from <loc> tags (sitemap format)
    loc_pattern = re.compile(r'<loc>(.*?)</loc>', re.DOTALL)
    loc_matches = loc_pattern.findall(content)
    
    if loc_matches:
        logging.info(f"Found {len(loc_matches)} URLs in <loc> tags")
        for url in loc_matches:
            urls.add(url.strip())
        return urls
    
    # If no <loc> tags found, try extracting from href attributes
    url_pattern = re.compile(r'href=[\'"]?([^\'" >]+)[\'"]?')
    matches = url_pattern.findall(content)
    
    parsed_base = urlparse(base_url)
    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
    
    for match in matches:
        # Skip anchors, javascript, mailto links
        if match.startswith(('#', 'javascript:', 'mailto:')):
            continue
            
        # Convert relative URLs to absolute
        if not match.startswith(('http://', 'https://')):
            if match.startswith('/'):
                match = f"{base_domain}{match}"
            else:
                match = urljoin(base_url, match)
                
        # Only include URLs from the same domain
        parsed_url = urlparse(match)
        if parsed_url.netloc == parsed_base.netloc:
            urls.add(match)
            
    logging.info(f"Regex extraction found {len(urls)} URLs")
    return urls

def url_to_filename(url):
    """Convert a URL to a valid filename."""
    # Replace protocol separator
    filename = url.replace('://', '_--')
    # Replace other invalid characters
    filename = filename.replace('/', '-').replace('\\', '-')
    filename = filename.replace(':', '_').replace('*', '_')
    filename = filename.replace('?', '_').replace('&', '_')
    filename = filename.replace('"', '_').replace("'", '_')
    filename = filename.replace('<', '_').replace('>', '_')
    filename = filename.replace('|', '_').replace(' ', '_')
    filename = filename.replace('#', '_').replace('%', '_')
    filename = filename.replace('+', '_').replace('=', '_')
    # Limit filename length to avoid issues with long paths
    if len(filename) > 200:
        filename = filename[:200]
    return filename

def get_cache_xml_filename(url, output_dir):
    """Generate a filename for caching a sitemap XML content."""
    if not output_dir:
        return None
        
    # Create a readable filename from the URL
    filename = url_to_filename(url) + ".xml"
    cache_xml_dir = os.path.join(output_dir, "cache-xml")
    return os.path.join(cache_xml_dir, filename)

def get_sitemap_urls(sitemap_url, output_dir=None, verbose=False):
    """Extract all URLs from a sitemap, handling different formats and recursion."""
    if verbose:
        logging.info(f"Fetching sitemap from {sitemap_url}")
    urls = set()
    url_sources = {}  # Dictionary to track where each URL was found
    content = ""
    
    try:
        response = requests.get(sitemap_url, timeout=10)
        response.raise_for_status()
        content = response.text
        
        # Cache the XML content if output_dir is provided
        if output_dir and content:
            try:
                cache_file = get_cache_xml_filename(sitemap_url, output_dir)
                if cache_file:
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                    if verbose:
                        logging.debug(f"Cached XML content for {sitemap_url}")
            except Exception as e:
                if verbose:
                    logging.warning(f"Failed to cache XML content for {sitemap_url}: {e}")
        
        # Try direct regex extraction of <loc> tags first (most reliable for malformed XML)
        loc_urls = extract_urls_with_regex(content, sitemap_url)
        if loc_urls:
            if verbose:
                logging.info(f"Found {len(loc_urls)} URLs using direct <loc> tag extraction")
            
            # Check if any of these are sitemaps themselves
            sitemap_urls = [url for url in loc_urls if 'sitemap' in url.lower() and url.endswith(('.xml', '.xml.gz'))]
            if sitemap_urls:
                if verbose:
                    logging.info(f"Found {len(sitemap_urls)} sub-sitemaps to process")
                for sub_sitemap_url in sitemap_urls:
                    sub_urls, sub_sources = get_sitemap_urls(sub_sitemap_url, output_dir, verbose)
                    urls.update(sub_urls)
                    url_sources.update(sub_sources)
                    
                # Remove the sitemap URLs from the regular URLs
                regular_urls = loc_urls - set(sitemap_urls)
                urls.update(regular_urls)
                # Track sources for regular URLs
                for url in regular_urls:
                    url_sources[url] = sitemap_url
            else:
                urls.update(loc_urls)
                # Track sources for all URLs
                for url in loc_urls:
                    url_sources[url] = sitemap_url
                
            if urls:
                if verbose:
                    logging.info(f"Successfully extracted URLs from sitemap, found {len(urls)} URLs")
                return urls, url_sources
        
        # If regex extraction didn't work, try standard XML parsing
        if content.strip().startswith('<?xml') or '<urlset' in content or '<sitemapindex' in content:
            try:
                # Handle XML sitemaps
                root = ET.fromstring(content)
                
                # Namespace handling
                namespaces = {
                    'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
                    'xhtml': 'http://www.w3.org/1999/xhtml'
                }
                
                # Check if this is a sitemap index
                sitemaps = root.findall('.//sm:sitemap/sm:loc', namespaces) or root.findall('.//sitemap/loc', {})
                
                if sitemaps:
                    if verbose:
                        logging.info(f"Found sitemap index with {len(sitemaps)} sitemaps")
                    for sitemap in sitemaps:
                        sub_sitemap_url = sitemap.text.strip()
                        sub_urls, sub_sources = get_sitemap_urls(sub_sitemap_url, output_dir, verbose)
                        urls.update(sub_urls)
                        url_sources.update(sub_sources)
                else:
                    # Regular sitemap
                    url_elements = (root.findall('.//sm:url/sm:loc', namespaces) or 
                                   root.findall('.//url/loc', {}))
                    
                    for url_element in url_elements:
                        url = url_element.text.strip()
                        urls.add(url)
                        url_sources[url] = sitemap_url
                        
                if urls:
                    if verbose:
                        logging.info(f"Successfully parsed XML sitemap, found {len(urls)} URLs")
                    return urls, url_sources
            except ET.ParseError as e:
                if verbose:
                    logging.error(f"XML parsing error in sitemap {sitemap_url}: {e}")
        
        # If XML parsing failed or it's not an XML sitemap, try HTML parsing
        if verbose:
            logging.info(f"Attempting to parse {sitemap_url} as HTML sitemap")
        
        # Try BeautifulSoup parsing
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # Look for links in the page
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                
                # Handle relative URLs
                if not href.startswith(('http://', 'https://')):
                    href = urljoin(sitemap_url, href)
                
                # Check if it's a sitemap link
                if 'sitemap' in href.lower() and href.endswith(('.xml', '.xml.gz')):
                    if verbose:
                        logging.info(f"Found sitemap link in HTML: {href}")
                    sub_urls = get_sitemap_urls(href, output_dir, verbose)
                    urls.update(sub_urls)
                else:
                    # Parse the URL to check if it's from the same domain
                    parsed_href = urlparse(href)
                    parsed_sitemap = urlparse(sitemap_url)
                    
                    if parsed_href.netloc == parsed_sitemap.netloc:
                        urls.add(href)
        except Exception as e:
            if verbose:
                logging.error(f"BeautifulSoup parsing error: {e}")
        
        # Check if it's a text sitemap (one URL per line)
        if not urls and all(line.startswith(('http://', 'https://')) for line in content.splitlines() if line.strip()):
            for line in content.splitlines():
                line = line.strip()
                if line and line.startswith(('http://', 'https://')):
                    urls.add(line)
        
        # If still no URLs found, use regex as a last resort
        if not urls:
            if verbose:
                logging.info("No URLs found with standard methods, trying regex extraction")
            regex_urls = extract_urls_with_regex(content, sitemap_url)
            urls.update(regex_urls)
        
        if verbose:
            logging.info(f"Found {len(urls)} URLs in sitemap {sitemap_url}")
        return urls, url_sources
    except Exception as e:
        if verbose:
            logging.error(f"Error fetching sitemap {sitemap_url}: {e}")
        # Try regex extraction as a last resort
        try:
            if verbose:
                logging.info("Attempting regex extraction after exception")
            regex_urls = extract_urls_with_regex(content, sitemap_url)
            urls.update(regex_urls)
            if verbose:
                logging.info(f"Regex extraction found {len(urls)} URLs after exception")
            # Add sources for regex-extracted URLs
            for url in regex_urls:
                url_sources[url] = sitemap_url
        except Exception as regex_error:
            if verbose:
                logging.error(f"Regex extraction also failed: {regex_error}")
        return urls, url_sources

def normalize_url(url):
    """Normalize URL to avoid duplicates due to trivial differences."""
    parsed = urlparse(url)
    
    # Remove trailing slash if present
    path = parsed.path
    if path.endswith('/') and path != '/':
        path = path[:-1]
    elif not path:
        path = '/'
        
    # Lowercase the domain
    netloc = parsed.netloc.lower()
    
    # Reconstruct URL without query parameters and fragments
    return f"{parsed.scheme}://{netloc}{path}"

def is_pagination_url(url):
    """Check if a URL appears to be a pagination URL."""
    # Common pagination patterns
    pagination_patterns = [
        r'/page/\d+/?$',           # /page/2/
        r'/p/\d+/?$',              # /p/2/
        r'/page-\d+/?$',           # /page-2/
        r'/\d+/?$',                # /2/
        r'\?page=\d+$',            # ?page=2
        r'\?p=\d+$',               # ?p=2
        r'\?pg=\d+$',              # ?pg=2
        r'\?paged=\d+$',           # ?paged=2
        r'\?offset=\d+$',          # ?offset=20
        r'\?start=\d+$',           # ?start=10
        r'\?from=\d+$',            # ?from=10
        r'\?pg=\d+$',              # ?pg=2
        r'\?[a-zA-Z0-9_-]+=\d+&page=\d+$',  # ?category=news&page=2
    ]
    
    for pattern in pagination_patterns:
        if re.search(pattern, url):
            return True
    return False

def is_category_or_tag_url(url):
    """Check if a URL appears to be a WordPress category or tag URL."""
    # Common WordPress category and tag patterns
    patterns = [
        # Category patterns
        r'/category/[^/]+/?$',          # /category/garden/
        r'/categories/[^/]+/?$',        # /categories/garden/
        r'/cat/[^/]+/?$',               # /cat/garden/
        r'\?cat=\d+$',                  # ?cat=5
        r'\?category=[\w-]+$',          # ?category=garden
        r'\?category_name=[\w-]+$',     # ?category_name=garden
        r'/topics/[^/]+/?$',            # /topics/garden/
        r'/subject/[^/]+/?$',           # /subject/garden/
        
        # Tag patterns
        r'/tag/[^/]+/?$',               # /tag/thing/
        r'/tags/[^/]+/?$',              # /tags/thing/
        r'\?tag=[\w-]+$',               # ?tag=thing
        r'/label/[^/]+/?$',             # /label/thing/
        r'/keyword/[^/]+/?$',           # /keyword/thing/
        r'/topic/[^/]+/?$',             # /topic/thing/
    ]
    
    for pattern in patterns:
        if re.search(pattern, url):
            return True
    return False

def is_valid_url(url):
    """Check if a URL is valid and should be included in results."""
    if not url:
        return False
        
    # Skip URLs with common non-content extensions
    skip_extensions = [
        # Style and script files
        '.css', '.js', '.json', '.xml', 
        # Images
        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.bmp', '.tiff', '.tif',
        # Fonts
        '.woff', '.woff2', '.ttf', '.eot', '.otf',
        # Documents
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp',
        # Archives
        '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2',
        # Media
        '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.wav', '.ogg', '.webm',
        # Other
        '.exe', '.dll', '.so', '.dmg', '.pkg'
    ]
    
    for ext in skip_extensions:
        if url.lower().endswith(ext):
            return False
            
    # Skip URLs with common query parameters that indicate non-content
    if any(param in url for param in ['?replytocom=', '?share=', '?like=']):
        return False
        
    return True

def get_cache_filename(url, cache_dir):
    """Generate a filename for caching a URL's content."""
    # Create a readable filename from the URL
    filename = url_to_filename(url) + ".html"
    return os.path.join(cache_dir, filename)

def spider_website(start_url, max_pages=10000, num_workers=4, output_dir=None, verbose=False):
    """Spider a website and return all discovered URLs using parallel workers."""
    global interrupted
    base_domain = urlparse(start_url).netloc
    
    # Use thread-safe collections
    visited_urls = set()
    found_urls = set()
    url_sources = {}  # Dictionary to track where each URL was found
    url_queue = queue.Queue()
    url_queue.put((start_url, None))  # (url, source_url) tuple
    
    # Locks for thread safety
    visited_lock = threading.Lock()
    found_lock = threading.Lock()
    
    # Counter for progress reporting
    visited_count = 0
    
    # Set up cache directory if output_dir is provided
    cache_dir = None
    if output_dir:
        cache_dir = os.path.join(output_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
    
    # Progress bar for non-verbose mode
    progress_bar = None
    # Start with a small initial estimate
    initial_estimate = 10
    if verbose:
        logging.info(f"Starting to spider {start_url} with {num_workers} parallel workers")
    else:
        print(f"Spidering website: {start_url}")
        progress_bar = tqdm(total=initial_estimate, desc="Pages crawled", unit="pages", dynamic_ncols=True)
    
    # Variables for progress tracking
    estimated_total = initial_estimate
    last_update_time = time.time()
    
    def process_url():
        nonlocal visited_count, last_update_time, estimated_total
        while not interrupted and visited_count < max_pages:
            try:
                # Get URL with timeout to allow for interruption
                try:
                    current_url, source_url = url_queue.get(timeout=1)  # Get URL and its source
                except queue.Empty:
                    # If queue is empty, check if all workers are idle
                    if url_queue.empty():
                        break
                    continue
                
                # Skip if already visited
                with visited_lock:
                    if current_url in visited_urls:
                        url_queue.task_done()
                        continue
                    visited_urls.add(current_url)
                    visited_count += 1
                    
                    # Update progress bar
                    if not verbose and progress_bar:
                        # Update the progress bar
                        progress_bar.update(1)
                        
                        # Periodically adjust the total based on queue size and visited count
                        current_time = time.time()
                        if current_time - last_update_time > 0.5:
                            new_estimate = max(len(visited_urls) + url_queue.qsize(), len(visited_urls) + 5)
                            if new_estimate > estimated_total:
                                estimated_total = new_estimate
                                progress_bar.total = estimated_total
                                progress_bar.refresh()
                            last_update_time = current_time
                
                if verbose:
                    logging.info(f"Visiting {current_url} ({visited_count}/{max_pages})")
                
                try:
                    # Implement exponential backoff for connection errors
                    retry_delays = [1, 2, 4, 8, 16, 32]
                    response = None
                    last_error = None
                    
                    for retry, delay in enumerate(retry_delays):
                        try:
                            response = requests.get(current_url, timeout=10)
                            break  # Success, exit retry loop
                        except Exception as e:
                            last_error = e
                            error_message = str(e).lower()
                            
                            # Only retry for connection-related errors
                            if any(err in error_message for err in [
                                'connection reset', 'connection timed out', 'timeout', 
                                'recv failure', 'operation timed out'
                            ]):
                                if retry < len(retry_delays) - 1:  # Don't log on last attempt
                                    if verbose:
                                        logging.warning(f"Connection error on {current_url}, retrying in {delay}s (attempt {retry+1}/{len(retry_delays)}): {e}")
                                    time.sleep(delay)
                                    continue
                            # For non-connection errors or last retry, don't retry
                            raise
                    
                    # If we exhausted all retries
                    if response is None:
                        raise last_error
                    
                    with found_lock:
                        found_urls.add(current_url)
                        # Set the source - if it's the start URL, it's its own source
                        if source_url is None:
                            url_sources[current_url] = current_url
                        else:
                            url_sources[current_url] = source_url
                    
                    # Skip non-HTML content types and binary files
                    content_type = response.headers.get('Content-Type', '').lower()
                    is_html = ('text/html' in content_type or 'application/xhtml+xml' in content_type)
                    
                    # Cache the content if it's HTML and we have a cache directory
                    if is_html and cache_dir:
                        try:
                            cache_file = get_cache_filename(current_url, cache_dir)
                            with open(cache_file, 'w', encoding='utf-8') as f:
                                f.write(response.text)
                            if verbose:
                                logging.debug(f"Cached content for {current_url}")
                        except Exception as e:
                            if verbose:
                                logging.warning(f"Failed to cache content for {current_url}: {e}")
                    
                    if not is_html:
                        url_queue.task_done()
                        continue
                        
                    # Skip URLs with file extensions we want to avoid
                    parsed_url = urlparse(current_url)
                    path = parsed_url.path.lower()
                    if any(path.endswith(ext) for ext in [
                        '.jpg', '.jpeg', '.png', '.gif', '.pdf', '.doc', '.docx', 
                        '.xls', '.xlsx', '.zip', '.rar', '.mp3', '.mp4', '.avi'
                    ]):
                        url_queue.task_done()
                        continue
                        
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Find all links
                    new_urls = []
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        full_url = urljoin(current_url, href)
                        
                        # Skip non-HTTP URLs, fragments, and external domains
                        parsed_url = urlparse(full_url)
                        if (parsed_url.scheme not in ('http', 'https') or 
                            parsed_url.netloc != base_domain or 
                            '#' in full_url):
                            continue
                            
                        # Remove fragments
                        clean_url = full_url.split('#')[0]
                        
                        # Skip binary and non-HTML file types before adding to queue
                        path = parsed_url.path.lower()
                        if any(path.endswith(ext) for ext in [
                            # Style and script files
                            '.css', '.js', '.json', '.xml', 
                            # Images
                            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.bmp', '.tiff', '.tif',
                            # Fonts
                            '.woff', '.woff2', '.ttf', '.eot', '.otf',
                            # Documents
                            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp',
                            # Archives
                            '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2',
                            # Media
                            '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.wav', '.ogg', '.webm',
                            # Other
                            '.exe', '.dll', '.so', '.dmg', '.pkg'
                        ]):
                            continue
                        
                        with visited_lock:
                            if clean_url not in visited_urls:
                                new_urls.append(clean_url)
                                # Track the source of this URL
                                if clean_url not in url_sources:
                                    url_sources[clean_url] = current_url
                    
                    # Add new URLs to the queue with current_url as their source
                    for url in new_urls:
                        url_queue.put((url, current_url))
                        
                        # No need to update estimated total here
                        
                except Exception as e:
                    if verbose:
                        logging.error(f"Error visiting {current_url}: {e}")
                
                url_queue.task_done()
                
            except Exception as e:
                if verbose:
                    logging.error(f"Worker error: {e}")
    
    try:
        # Create and start worker threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            workers = [executor.submit(process_url) for _ in range(num_workers)]
            
            # Wait for all tasks to complete or for interruption
            while not interrupted and visited_count < max_pages and not url_queue.empty():
                # Check if all workers are done
                if all(worker.done() for worker in workers):
                    break
                # Sleep briefly to avoid busy waiting
                threading.Event().wait(0.1)
            
            # If interrupted, cancel remaining workers
            if interrupted:
                for worker in workers:
                    worker.cancel()
    
    except Exception as e:
        if verbose:
            logging.error(f"Spidering error: {e}")
        
    if interrupted:
        if verbose:
            logging.info("Spidering interrupted. Returning URLs found so far...")
    
    # Close progress bar if it exists
    if not verbose and progress_bar:
        # Set the final total to the actual number of URLs visited
        progress_bar.total = len(visited_urls)
        progress_bar.refresh()
        progress_bar.close()
        
    if verbose:
        logging.info(f"Spidering complete. Found {len(found_urls)} URLs")
    else:
        print(f"Spidering complete. Found {len(found_urls)} URLs")
    return found_urls, url_sources

def find_previous_scan(current_dir, domain):
    """Find the most recent previous scan directory for the given domain."""
    sites_dir = os.path.join("sites", domain)
    if not os.path.exists(sites_dir):
        return None
        
    # Get all timestamp directories for this domain
    timestamp_dirs = []
    for dirname in os.listdir(sites_dir):
        dir_path = os.path.join(sites_dir, dirname)
        if os.path.isdir(dir_path) and dir_path != current_dir:
            # Check if this directory has the required CSV files - only require all_site_urls.csv
            if os.path.exists(os.path.join(dir_path, "all_site_urls.csv")):
                timestamp_dirs.append(dir_path)
    
    if not timestamp_dirs:
        return None
        
    # Sort by modification time (most recent first)
    timestamp_dirs.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return timestamp_dirs[0]

def compare_csv_files(current_file, previous_file, output_file, verbose=False):
    """Compare two CSV files and write differences to output file."""
    # Read current CSV
    current_urls = set()
    with open(current_file, 'r', newline='') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            if len(row) >= 2:
                current_urls.add(row[1])  # URL is in second column
    
    # Read previous CSV
    previous_urls = set()
    with open(previous_file, 'r', newline='') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            if len(row) >= 2:
                previous_urls.add(row[1])  # URL is in second column
    
    # Find new and fixed issues
    new_issues = current_urls - previous_urls
    fixed_issues = previous_urls - current_urls
    
    # Write comparison results
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Status", "URL"])
        
        for url in sorted(new_issues):
            writer.writerow(["New", url])
            
        for url in sorted(fixed_issues):
            writer.writerow(["Fixed", url])
    
    if verbose:
        logging.info(f"Comparison found {len(new_issues)} new issues and {len(fixed_issues)} fixed issues")
    else:
        print(f"Comparison found {len(new_issues)} new issues and {len(fixed_issues)} fixed issues")
    
    return len(new_issues), len(fixed_issues)

def create_output_directory(start_url):
    """Create a directory structure for output files based on the URL and timestamp."""
    # Extract domain from URL
    domain = urlparse(start_url).netloc
    
    # Create timestamp
    now = datetime.datetime.now()
    timestamp = now.strftime("%m-%d-%Y_%I-%M%p").lower()
    
    # Create directory structure
    base_dir = os.path.join("sites", domain, timestamp)
    os.makedirs(base_dir, exist_ok=True)
    
    # Create cache directories
    cache_dir = os.path.join(base_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    
    cache_xml_dir = os.path.join(base_dir, "cache-xml")
    os.makedirs(cache_xml_dir, exist_ok=True)
    
    logging.info(f"Created output directory: {base_dir}")
    return base_dir

def cache_missing_urls(urls, output_dir, verbose=False):
    """Fetch and cache URLs that are in the sitemap but not found by spidering."""
    if not urls:
        if verbose:
            logging.info("No missing URLs to cache")
        return
        
    cache_xml_dir = os.path.join(output_dir, "cache-xml")
    os.makedirs(cache_xml_dir, exist_ok=True)
    
    # Progress bar for non-verbose mode
    pbar = None
    if verbose:
        logging.info(f"Caching {len(urls)} URLs found in sitemap but not in site spider")
    else:
        print(f"Caching {len(urls)} missing URLs")
        pbar = tqdm(total=len(urls), desc="Caching URLs", unit="urls")
    
    # Retry delays for exponential backoff
    retry_delays = [1, 2, 4, 8, 16, 32]
    
    for i, url in enumerate(sorted(urls)):
        if interrupted:
            if verbose:
                logging.info("Caching interrupted. Exiting...")
            if not verbose and pbar:
                pbar.close()
            break
            
        if verbose:
            logging.info(f"Caching URL {i+1}/{len(urls)}: {url}")
        
        # Generate cache filename
        filename = url_to_filename(url) + ".html"
        cache_file = os.path.join(cache_xml_dir, filename)
        
        # Skip if already cached
        if os.path.exists(cache_file):
            if verbose:
                logging.info(f"URL already cached: {url}")
            if not verbose and pbar:
                pbar.update(1)
            continue
            
        # Fetch with retry
        for retry, delay in enumerate(retry_delays):
            try:
                response = requests.get(url, timeout=10)
                
                # Cache the content
                with open(cache_file, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                if verbose:
                    logging.info(f"Successfully cached: {url}")
                if not verbose and pbar:
                    pbar.update(1)
                break
            except Exception as e:
                error_message = str(e).lower()
                if any(err in error_message for err in [
                    'connection reset', 'connection timed out', 'timeout', 
                    'recv failure', 'operation timed out'
                ]):
                    if retry < len(retry_delays) - 1:
                        if verbose:
                            logging.warning(f"Connection error caching {url}, retrying in {delay}s (attempt {retry+1}/{len(retry_delays)}): {e}")
                        time.sleep(delay)
                        continue
                if verbose:
                    logging.error(f"Failed to cache {url}: {e}")
                break

def main():
    global interrupted
    try:
        # Create output directory
        output_dir = create_output_directory(args.start_url)
        
        # Get verbose flag
        verbose = args.verbose
        
        # Get sitemap URL (discover if not provided)
        sitemap_url = args.sitemap_url
        sitemap_urls = set()
        sitemap_sources = {}
        normalized_sitemap_sources = {}
        
        if not sitemap_url:
            sitemap_url = discover_sitemap_url(args.start_url, output_dir, verbose)
            
        if not sitemap_url:
            if verbose:
                logging.warning("Could not discover sitemap. Continuing with site spider only.")
            else:
                print("No sitemap found. Continuing with site spider only.")
            # Set an empty set for sitemap URLs
            sitemap_urls_raw = set()
            has_sitemap = False
        else:
            # Get URLs from sitemap
            if not verbose:
                print("Extracting URLs from sitemap...")
            sitemap_urls_raw, sitemap_sources = get_sitemap_urls(sitemap_url, output_dir, verbose)
            has_sitemap = True
        
        # Filter and normalize sitemap URLs
        for url in sitemap_urls_raw:
            if is_valid_url(url):
                normalized_url = normalize_url(url)
                sitemap_urls.add(normalized_url)
                normalized_sitemap_sources[normalized_url] = sitemap_sources.get(url, sitemap_url if sitemap_url else args.start_url)
        
        if has_sitemap:
            if verbose:
                logging.info(f"After filtering and normalization, found {len(sitemap_urls)} valid URLs in sitemap")
            else:
                print(f"Found {len(sitemap_urls)} valid URLs in sitemap")
        
        # Get URLs from spidering
        site_urls_raw, site_sources = spider_website(args.start_url, max_pages=args.max_pages, 
                                      num_workers=args.workers, output_dir=output_dir, 
                                      verbose=verbose)
        
        # Filter and normalize site URLs
        site_urls = set()
        normalized_site_sources = {}  # Track sources for normalized URLs
        for url in site_urls_raw:
            if is_valid_url(url):
                normalized_url = normalize_url(url)
                site_urls.add(normalized_url)
                normalized_site_sources[normalized_url] = site_sources.get(url, args.start_url)
                
        if verbose:
            logging.info(f"After filtering and normalization, found {len(site_urls)} valid URLs from spidering")
        else:
            print(f"Found {len(site_urls)} valid URLs from spidering")
        
        # Check if we were interrupted
        if interrupted:
            logging.info("Process was interrupted. Exiting...")
            sys.exit(0)
            
        # Find differences
        filtered_site_urls = site_urls.copy()

        # Apply pagination filtering if requested
        if args.ignore_pagination:
            before_count = len(filtered_site_urls)
            filtered_site_urls = {url for url in filtered_site_urls if not is_pagination_url(url)}
            pagination_filtered = before_count - len(filtered_site_urls)
            
            if verbose:
                logging.info(f"Filtered out {pagination_filtered} pagination URLs")
            else:
                print(f"Ignored {pagination_filtered} pagination URLs")

        # Apply category and tag filtering if requested
        if args.ignore_categories_tags:
            before_count = len(filtered_site_urls)
            filtered_site_urls = {url for url in filtered_site_urls if not is_category_or_tag_url(url)}
            category_tag_filtered = before_count - len(filtered_site_urls)
            
            if verbose:
                logging.info(f"Filtered out {category_tag_filtered} WordPress category and tag URLs")
            else:
                print(f"Ignored {category_tag_filtered} WordPress category and tag URLs")
                
        in_site_not_sitemap = filtered_site_urls - sitemap_urls
            
        in_sitemap_not_site = sitemap_urls - site_urls
        
        # Write results to CSV files in the output directory
        missing_from_sitemap_file = os.path.join(output_dir, "missing_from_sitemap.csv")
        with open(missing_from_sitemap_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Source", "URL"])
            for url in sorted(in_site_not_sitemap):
                writer.writerow([normalized_site_sources.get(url, args.start_url), url])
        if verbose:
            logging.info(f"Wrote {len(in_site_not_sitemap)} URLs missing from sitemap to {missing_from_sitemap_file}")
        else:
            print(f"Found {len(in_site_not_sitemap)} URLs missing from sitemap")
        
        # Handle sitemap-related output files based on whether we have a sitemap
        if has_sitemap:
            missing_from_site_file = os.path.join(output_dir, "missing_from_site.csv")
            with open(missing_from_site_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "URL"])
                for url in sorted(in_sitemap_not_site):
                    writer.writerow([normalized_sitemap_sources.get(url, sitemap_url if sitemap_url else args.start_url), url])
            if verbose:
                logging.info(f"Wrote {len(in_sitemap_not_site)} URLs missing from site to {missing_from_site_file}")
            else:
                print(f"Found {len(in_sitemap_not_site)} URLs missing from site")
            
            # Cache pages that are in sitemap but not found by site spider
            cache_missing_urls(in_sitemap_not_site, output_dir, verbose)
            
            # Write all sitemap URLs to CSV file for reference
            all_sitemap_urls_file = os.path.join(output_dir, "all_sitemap_urls.csv")
            with open(all_sitemap_urls_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "URL"])
                for url in sorted(sitemap_urls):
                    writer.writerow([normalized_sitemap_sources.get(url, sitemap_url if sitemap_url else args.start_url), url])
        else:
            # Create empty files for consistency
            with open(os.path.join(output_dir, "missing_from_site.csv"), 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "URL"])
                writer.writerow(["No sitemap found", ""])
            
            with open(os.path.join(output_dir, "all_sitemap_urls.csv"), 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "URL"])
                writer.writerow(["No sitemap found", ""])
        
        # Write all site URLs to CSV file for reference
        all_site_urls_file = os.path.join(output_dir, "all_site_urls.csv")
        with open(all_site_urls_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Source", "URL"])
            for url in sorted(site_urls):
                writer.writerow([normalized_site_sources.get(url, args.start_url), url])
        
        # Compare with previous scan if requested
        if args.compare_previous:
            domain = urlparse(args.start_url).netloc
            previous_dir = find_previous_scan(output_dir, domain)
            
            if previous_dir:
                if verbose:
                    logging.info(f"Comparing with previous scan: {previous_dir}")
                else:
                    print(f"\nComparing with previous scan: {os.path.basename(previous_dir)}")
                
                # Compare missing from site
                current_missing_site = os.path.join(output_dir, "missing_from_site.csv")
                previous_missing_site = os.path.join(previous_dir, "missing_from_site.csv")
                comparison_missing_site = os.path.join(output_dir, "comparison_missing_from_site.csv")
                
                new_missing_site, fixed_missing_site = compare_csv_files(
                    current_missing_site, previous_missing_site, comparison_missing_site, verbose)
                
                # Compare missing from sitemap
                current_missing_sitemap = os.path.join(output_dir, "missing_from_sitemap.csv")
                previous_missing_sitemap = os.path.join(previous_dir, "missing_from_sitemap.csv")
                comparison_missing_sitemap = os.path.join(output_dir, "comparison_missing_from_sitemap.csv")
                
                new_missing_sitemap, fixed_missing_sitemap = compare_csv_files(
                    current_missing_sitemap, previous_missing_sitemap, comparison_missing_sitemap, verbose)
                
                if verbose:
                    logging.info("Comparison with previous scan complete")
                else:
                    print("\nComparison with previous scan complete")
                    print(f"Missing from site: {new_missing_site} new, {fixed_missing_site} fixed")
                    print(f"Missing from sitemap: {new_missing_sitemap} new, {fixed_missing_sitemap} fixed")
            else:
                if verbose:
                    logging.warning("No previous scan found for comparison")
                else:
                    print("\nNo previous scan found for comparison")
        
        if verbose:
            logging.info("Comparison complete!")
        else:
            print("\nComparison complete!")
            print(f"Results saved to: {output_dir}")
    except Exception as e:
        logging.error(f"Error in main process: {e}")
        sys.exit(1)
    finally:
        if interrupted:
            if verbose:
                logging.info("Process interrupted by user. Exiting...")
            else:
                print("\nProcess interrupted by user. Exiting...")
            sys.exit(0)

if __name__ == "__main__":
    main()
