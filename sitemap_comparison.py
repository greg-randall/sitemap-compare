import argparse
import re
import signal
import sys
import concurrent.futures
from urllib.parse import urlparse, urljoin
import urllib.parse
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

# Global constants for file extensions to skip
SKIP_EXTENSIONS = [
    # Style and script files
    '.css', '.js', '.json', '.xml', '.xsl', '.xslt', '.scss', '.sass', '.less',
    # Images
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.bmp', '.tiff', '.tif', '.avif', '.heic', '.heif',
    # Fonts
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    # Documents
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp', '.csv', '.rtf', '.txt', '.md',
    # Archives
    '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.tgz',
    # Media
    '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.wav', '.ogg', '.webm', '.m4a', '.m4v', '.mkv', '.3gp', '.aac',
    # Other
    '.exe', '.dll', '.so', '.dmg', '.pkg', '.apk', '.deb', '.rpm',
    # Data formats
    '.sqlite', '.db', '.sql', '.yaml', '.yml', '.toml', '.ini', '.config',
    # Web specific
    '.htaccess', '.htpasswd', '.map', '.min.js', '.min.css',
    # Programming languages
    '.py', '.java', '.class', '.c', '.cpp', '.h', '.hpp', '.cs', '.php', '.rb', '.go', '.rs', '.swift',
    # Config files
    '.conf', '.cfg', '.env'
]

# Additional constants for common non-content URLs
SKIP_QUERY_PARAMS = ['?replytocom=', '?share=', '?like=', '?print=']


class ThreadMonitor:
    def __init__(self, max_thread_time=60):  # Default 60 seconds max per thread
        self.max_thread_time = max_thread_time
        self.thread_start_times = {}
        self.thread_lock = threading.Lock()
        self.monitor_running = False
        self.monitor_thread = None
    
    def start_monitoring(self):
        """Start the monitoring thread"""
        self.monitor_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_threads, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        self.monitor_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1.0)
    
    def register_thread_start(self, thread_id):
        """Register the start time of a thread operation"""
        with self.thread_lock:
            self.thread_start_times[thread_id] = time.time()
    
    def register_thread_end(self, thread_id):
        """Register the completion of a thread operation"""
        with self.thread_lock:
            if thread_id in self.thread_start_times:
                del self.thread_start_times[thread_id]
    
    def _monitor_threads(self):
        """Monitor thread that checks for stuck threads"""
        while self.monitor_running:
            current_time = time.time()
            stuck_threads = []
            
            with self.thread_lock:
                for thread_id, start_time in list(self.thread_start_times.items()):
                    elapsed = current_time - start_time
                    if elapsed > self.max_thread_time:
                        stuck_threads.append((thread_id, elapsed))
                        # Remove from tracking to avoid repeated warnings
                        del self.thread_start_times[thread_id]
            
            # Log any stuck threads
            for thread_id, elapsed in stuck_threads:
                logging.warning(f"Thread {thread_id} exceeded time limit! Running for {elapsed:.1f}s (limit: {self.max_thread_time}s)")
            
            # Sleep for a short time before checking again
            time.sleep(1.0)

class Config:
    def __init__(self, args):
        self.start_url = args.start_url
        self.sitemap_url = args.sitemap_url
        self.output_prefix = args.output_prefix
        self.workers = args.workers
        self.max_pages = args.max_pages
        self.verbose = args.verbose
        self.compare_previous = args.compare_previous
        self.ignore_pagination = args.ignore_pagination
        self.ignore_categories_tags = args.ignore_categories_tags
        self.thread_timeout = args.thread_timeout
        
        # Parse domain from URL
        self.domain = urlparse(self.start_url).netloc
        
        # Create timestamp
        now = datetime.datetime.now()
        self.timestamp = now.strftime("%m-%d-%Y_%I-%M%p").lower()
        
        # Set up output directory
        self.output_dir = os.path.join("sites", self.domain, self.timestamp)


class UrlProcessor:
    def __init__(self, config):
        self.config = config
        
    def normalize_url(self, url):
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
    
    def is_valid_url(self, url):
        """Check if a URL is valid and should be included in results."""
        if not url:
            return False
            
        # Skip URLs with common non-content extensions
        for ext in SKIP_EXTENSIONS:
            if url.lower().endswith(ext):
                return False
                
        # Skip URLs with common query parameters that indicate non-content
        for param in SKIP_QUERY_PARAMS:
            if param in url:
                return False
            
        return True
    
    def is_pagination_url(self, url):
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
    
    def is_category_or_tag_url(self, url):
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
    
    def filter_urls(self, urls):
        """Filter URLs based on configuration settings."""
        filtered_urls = set()
        for url in urls:
            if self.is_valid_url(url):
                normalized_url = self.normalize_url(url)
                filtered_urls.add(normalized_url)
                
        # Apply pagination filtering if requested
        if self.config.ignore_pagination:
            filtered_urls = {url for url in filtered_urls if not self.is_pagination_url(url)}
            
        # Apply category and tag filtering if requested
        if self.config.ignore_categories_tags:
            filtered_urls = {url for url in filtered_urls if not self.is_category_or_tag_url(url)}
            
        return filtered_urls


class CacheManager:
    def __init__(self, config):
        self.config = config
        self.output_dir = config.output_dir
        self.verbose = config.verbose
        
    def url_to_filename(self, url):
        """Turn a URL into a safe file name."""
        filename = urllib.parse.quote(url, safe='-_.')
        # Cut the name if it's too long.
        return filename[:200]
    
    def cache_content(self, url, content, is_sitemap=False):
        """Cache content to a file."""
        if not self.output_dir:
            return
            
        try:
            # Determine which directory to use
            if is_sitemap:
                cache_dir = os.path.join(self.output_dir, "cache-xml")
                file_ext = ".xml"
            else:
                cache_dir = os.path.join(self.output_dir, "cache")
                file_ext = ".html"
                
            # Create directory if it doesn't exist
            os.makedirs(cache_dir, exist_ok=True)
            
            # Create the file path
            filename = self.url_to_filename(url) + file_ext
            file_path = os.path.join(cache_dir, filename)
            
            # Write content to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            if self.verbose:
                logging.debug(f"Cached content for {url}")
        except Exception as e:
            if self.verbose:
                logging.warning(f"Failed to cache content for {url}: {e}")
    
    def compress_output_files(self):
        """Copy output CSV files to a results directory."""
        # List of CSV files to copy
        csv_files = [
            "missing_from_sitemap.csv",
            "missing_from_site.csv",
            "all_sitemap_urls.csv",
            "all_site_urls.csv",
            "comparison_missing_from_site.csv",
            "comparison_missing_from_sitemap.csv"
        ]
        
        # Create the results directory
        results_dir = os.path.join(self.output_dir, "results")
        os.makedirs(results_dir, exist_ok=True)
        
        # Check which files exist
        files_to_copy = []
        total_size = 0
        
        for filename in csv_files:
            file_path = os.path.join(self.output_dir, filename)
            if os.path.exists(file_path):
                files_to_copy.append((file_path, filename))
                total_size += os.path.getsize(file_path)
        
        if not files_to_copy:
            if self.verbose:
                logging.info("No output files found to copy")
            return False
        
        if self.verbose:
            logging.info(f"Copying {len(files_to_copy)} output files (total size: {total_size / 1024:.2f} KB)")
        else:
            print(f"Copying {len(files_to_copy)} output files (total size: {total_size / 1024:.2f} KB)")
        
        try:
            # Copy each file to the results directory
            for file_path, filename in files_to_copy:
                dest_path = os.path.join(results_dir, filename)
                import shutil
                shutil.copy2(file_path, dest_path)
            
            if self.verbose:
                logging.info(f"Successfully copied output files to {results_dir}")
            else:
                print(f"Successfully copied output files to results directory")
            
            return True
        
        except Exception as e:
            if self.verbose:
                logging.error(f"Error copying output files: {str(e)}")
            else:
                print(f"Error copying output files: {str(e)}")
            return False
class SitemapFetcher:
    def __init__(self, config, cache_manager, url_processor):
        self.config = config
        self.cache_manager = cache_manager
        self.url_processor = url_processor
        self.verbose = config.verbose
        
    def discover_sitemap_url(self):
        """Try to automatically discover the sitemap URL."""
        base_url = self.config.start_url
        output_dir = self.config.output_dir
        verbose = self.verbose
        
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
        
        # Check robots.txt first (most reliable method)
        robots_url = f"{base_domain}/robots.txt"
        if verbose:
            logging.info(f"Checking robots.txt at {robots_url}")
        
        try:
            response = requests.get(robots_url, timeout=3)
            
            if response.status_code == 200:
                # Look for Sitemap: directive in robots.txt
                for line in response.text.splitlines():
                    if line.lower().startswith('sitemap:'):
                        sitemap_url = line.split(':', 1)[1].strip()
                        if verbose:
                            logging.info(f"Found sitemap in robots.txt: {sitemap_url}")
                        else:
                            print(f"Found sitemap in robots.txt: {sitemap_url}")
                    
                        # Cache the robots.txt file
                        self.cache_manager.cache_content(robots_url, response.text, is_sitemap=True)
                        return sitemap_url
        except Exception as e:
            if verbose:
                logging.warning(f"Error checking robots.txt: {e}")
        
        # Try common locations
        for url in potential_locations:
            if verbose:
                logging.info(f"Checking potential sitemap at {url}")
            
            try:
                response = requests.get(url, timeout=3)
                if response.status_code == 200 and ('<urlset' in response.text or '<sitemapindex' in response.text):
                    if verbose:
                        logging.info(f"Found sitemap at {url}")
                    else:
                        print(f"Found sitemap at {url}")
                    return url
            except Exception as e:
                if verbose:
                    logging.warning(f"Error checking {url}: {e}")
        
        if verbose:
            logging.error("Could not automatically discover sitemap")
        else:
            print("Could not automatically discover sitemap")
        return None

    def extract_urls_with_regex(self, content, base_url):
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
        
        # Get domain without www for comparison
        base_netloc_no_www = parsed_base.netloc
        if base_netloc_no_www.startswith('www.'):
            base_netloc_no_www = base_netloc_no_www[4:]
        
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
                    
            # Only include URLs from the same domain (allowing www and non-www variants)
            parsed_url = urlparse(match)
            url_netloc_no_www = parsed_url.netloc
            if url_netloc_no_www.startswith('www.'):
                url_netloc_no_www = url_netloc_no_www[4:]
                
            if (parsed_url.netloc == parsed_base.netloc or 
                url_netloc_no_www == base_netloc_no_www):
                urls.add(match)
                
        logging.info(f"Regex extraction found {len(urls)} URLs")
        return urls

    def get_sitemap_urls(self, sitemap_url):
        """Extract all URLs from a sitemap, handling different formats and recursion."""
        if self.verbose:
            logging.info(f"Fetching sitemap from {sitemap_url}")
        urls = set()
        url_sources = {}  # Dictionary to track where each URL was found
        content = ""
        
        try:
            response = requests.get(sitemap_url, timeout=3)
            response.raise_for_status()
            content = response.text
            
            # Cache the XML content
            self.cache_manager.cache_content(sitemap_url, content, is_sitemap=True)
            
            # Try direct regex extraction of <loc> tags first (most reliable for malformed XML)
            loc_urls = self.extract_urls_with_regex(content, sitemap_url)
            if loc_urls:
                if self.verbose:
                    logging.info(f"Found {len(loc_urls)} URLs using direct <loc> tag extraction")
                
                # Check if any of these are sitemaps themselves
                sitemap_urls = [url for url in loc_urls if (
                    # Check for common sitemap indicators in the URL
                    ('sitemap' in url.lower() or 'site-map' in url.lower() or 'site_map' in url.lower()) or
                    # Check for common sitemap file extensions
                    url.lower().endswith(('.xml', '.xml.gz', '.gz', '.txt')) or
                    # Check for URL patterns that might indicate a sitemap
                    ('/sitemap/' in url.lower() or '/sitemaps/' in url.lower() or 
                     '/sitemap_' in url.lower() or '/sitemap-' in url.lower())
                ) and not url.endswith(('.css', '.js', '.jpg', '.jpeg', '.png', '.gif'))]  # Exclude obvious non-sitemap files
                
                if sitemap_urls:
                    if self.verbose:
                        logging.info(f"Found {len(sitemap_urls)} sub-sitemaps to process")
                    for sub_sitemap_url in sitemap_urls:
                        sub_urls, sub_sources = self.get_sitemap_urls(sub_sitemap_url)
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
                    if self.verbose:
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
                        if self.verbose:
                            logging.info(f"Found sitemap index with {len(sitemaps)} sitemaps")
                        for sitemap in sitemaps:
                            sub_sitemap_url = sitemap.text.strip()
                            sub_urls, sub_sources = self.get_sitemap_urls(sub_sitemap_url)
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
                        if self.verbose:
                            logging.info(f"Successfully parsed XML sitemap, found {len(urls)} URLs")
                        return urls, url_sources
                except ET.ParseError as e:
                    if self.verbose:
                        logging.error(f"XML parsing error in sitemap {sitemap_url}: {e}")
            
            # If XML parsing failed or it's not an XML sitemap, try HTML parsing
            if self.verbose:
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
                        if self.verbose:
                            logging.info(f"Found sitemap link in HTML: {href}")
                        sub_urls, sub_sources = self.get_sitemap_urls(href)
                        urls.update(sub_urls)
                        url_sources.update(sub_sources)
                    else:
                        # Parse the URL to check if it's from the same domain
                        parsed_href = urlparse(href)
                        parsed_sitemap = urlparse(sitemap_url)
                        
                        if parsed_href.netloc == parsed_sitemap.netloc:
                            urls.add(href)
                            url_sources[href] = sitemap_url
            except Exception as e:
                if self.verbose:
                    logging.error(f"BeautifulSoup parsing error: {e}")
            
            # Check if it's a text sitemap (one URL per line)
            if not urls and all(line.startswith(('http://', 'https://')) for line in content.splitlines() if line.strip()):
                for line in content.splitlines():
                    line = line.strip()
                    if line and line.startswith(('http://', 'https://')):
                        urls.add(line)
                        url_sources[line] = sitemap_url
            
            # If still no URLs found, use regex as a last resort
            if not urls:
                if self.verbose:
                    logging.info("No URLs found with standard methods, trying regex extraction")
                regex_urls = self.extract_urls_with_regex(content, sitemap_url)
                urls.update(regex_urls)
                # Add sources for regex-extracted URLs
                for url in regex_urls:
                    url_sources[url] = sitemap_url
            
            if self.verbose:
                logging.info(f"Found {len(urls)} URLs in sitemap {sitemap_url}")
            return urls, url_sources
        except Exception as e:
            if self.verbose:
                logging.error(f"Error fetching sitemap {sitemap_url}: {e}")
            # Try regex extraction as a last resort
            try:
                if self.verbose:
                    logging.info("Attempting regex extraction after exception")
                regex_urls = self.extract_urls_with_regex(content, sitemap_url)
                urls.update(regex_urls)
                if self.verbose:
                    logging.info(f"Regex extraction found {len(urls)} URLs after exception")
                # Add sources for regex-extracted URLs
                for url in regex_urls:
                    url_sources[url] = sitemap_url
            except Exception as regex_error:
                if self.verbose:
                    logging.error(f"Regex extraction also failed: {regex_error}")
            return urls, url_sources

class WebsiteSpider:
    def __init__(self, config, cache_manager, url_processor):
        self.config = config
        self.cache_manager = cache_manager
        self.url_processor = url_processor
        self.verbose = config.verbose
        self.interrupted = False
        # Add thread monitor with configurable timeout
        self.thread_monitor = ThreadMonitor(max_thread_time=config.thread_timeout)
        
    def set_interrupted(self):
        """Set the interrupted flag."""
        self.interrupted = True

    def spider_website(self):
        """Spider a website and return all discovered URLs using parallel workers."""
        start_url = self.config.start_url
        max_pages = self.config.max_pages
        num_workers = self.config.workers
        output_dir = self.config.output_dir
        verbose = self.verbose
        
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
        
        # Start the thread monitor
        self.thread_monitor.start_monitoring()
        
        def process_url():
            nonlocal visited_count, last_update_time, estimated_total
            while not self.interrupted and visited_count < max_pages:
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
                    
                    # Generate a unique ID for this thread operation
                    thread_op_id = f"spider-{threading.get_ident()}-{hash(current_url) % 10000}"
                    self.thread_monitor.register_thread_start(thread_op_id)
                    
                    try:
                        # Implement exponential backoff for connection errors
                        retry_delays = [2, 4, 8, 16, 32]
                        response = None
                        last_error = None
                        
                        for retry, delay in enumerate(retry_delays):
                            try:
                                response = requests.get(current_url, timeout=3)
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
                        
                        # Cache the content if it's HTML
                        if is_html:
                            self.cache_manager.cache_content(current_url, response.text, is_sitemap=False)
                        
                        if not is_html:
                            url_queue.task_done()
                            continue
                            
                        # Skip URLs with file extensions we want to avoid
                        parsed_url = urlparse(current_url)
                        path = parsed_url.path.lower()
                        if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
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
                            if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
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
                            
                    except Exception as e:
                        if verbose:
                            logging.error(f"Error visiting {current_url}: {e}")
                    
                    finally:
                        # Always mark the thread operation as complete
                        self.thread_monitor.register_thread_end(thread_op_id)
                        url_queue.task_done()
                    
                except Exception as e:
                    if verbose:
                        logging.error(f"Worker error: {e}")
        
        try:
            # Create and start worker threads
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                workers = [executor.submit(process_url) for _ in range(num_workers)]
                
                # Wait for all tasks to complete or for interruption
                while not self.interrupted and visited_count < max_pages and not url_queue.empty():
                    # Check if all workers are done
                    if all(worker.done() for worker in workers):
                        break
                    # Sleep briefly to avoid busy waiting
                    threading.Event().wait(0.1)
                
                # If interrupted, cancel remaining workers
                if self.interrupted:
                    for worker in workers:
                        worker.cancel()
        
        except Exception as e:
            if verbose:
                logging.error(f"Spidering error: {e}")
        
        finally:
            # Stop the thread monitor
            self.thread_monitor.stop_monitoring()
            
        if self.interrupted:
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

    def cache_missing_urls(self, urls):
        """Fetch and cache URLs that are in the sitemap but not found by spidering."""
        if not urls:
            if self.verbose:
                logging.info("No missing URLs to cache")
            return
        
        # Convert to list and sort for consistent processing
        url_list = sorted(urls)
        total_urls = len(url_list)
        num_workers = self.config.workers
        
        # Progress tracking
        if self.verbose:
            logging.info(f"Caching {total_urls} URLs found in sitemap but not in site spider using {num_workers} workers")
        else:
            print(f"Caching {total_urls} missing URLs using {num_workers} workers")
        
        # Use a thread-safe counter for progress tracking
        processed_count = 0
        counter_lock = threading.Lock()
        
        # Progress bar for non-verbose mode
        pbar = None
        if not self.verbose:
            pbar = tqdm(total=total_urls, desc="Caching URLs", unit="urls")
        
        # Retry delays for exponential backoff
        retry_delays = [2, 4, 8, 16, 32]
        
        # Start the thread monitor
        self.thread_monitor.start_monitoring()
        
        def cache_url(url):
            nonlocal processed_count
            
            if self.interrupted:
                return
            
            # Generate a unique ID for this thread operation
            thread_op_id = f"cache-{threading.get_ident()}-{hash(url) % 10000}"
            self.thread_monitor.register_thread_start(thread_op_id)
            
            try:
                # Generate cache filename for checking
                filename = self.cache_manager.url_to_filename(url) + ".html"
                    
                # Fetch with retry
                for retry, delay in enumerate(retry_delays):
                    if self.interrupted:
                        return
                        
                    try:
                        response = requests.get(url, timeout=3)
                        
                        # Cache the content
                        self.cache_manager.cache_content(url, response.text, is_sitemap=True)
                        if self.verbose:
                            logging.info(f"Successfully cached: {url}")
                        break
                    except Exception as e:
                        error_message = str(e).lower()
                        if any(err in error_message for err in [
                            'connection reset', 'connection timed out', 'timeout', 
                            'recv failure', 'operation timed out'
                        ]):
                            if retry < len(retry_delays) - 1 and not self.interrupted:
                                if self.verbose:
                                    logging.warning(f"Connection error caching {url}, retrying in {delay}s (attempt {retry+1}/{len(retry_delays)}): {e}")
                                time.sleep(delay)
                                continue
                        if self.verbose:
                            logging.error(f"Failed to cache {url}: {e}")
                        break
            
            finally:
                # Always mark the thread operation as complete
                self.thread_monitor.register_thread_end(thread_op_id)
                
                # Update progress
                with counter_lock:
                    processed_count += 1
                    if not self.verbose and pbar:
                        pbar.update(1)
        
        try:
            # Use ThreadPoolExecutor to process URLs in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                # Submit all URLs to the executor
                futures = [executor.submit(cache_url, url) for url in url_list]
                
                # Wait for all tasks to complete or for interruption
                for future in concurrent.futures.as_completed(futures):
                    if self.interrupted:
                        break
                    try:
                        future.result()  # Get the result to catch any exceptions
                    except Exception as e:
                        if self.verbose:
                            logging.error(f"Error in worker thread: {e}")
        
        except Exception as e:
            if self.verbose:
                logging.error(f"Error in cache_missing_urls: {e}")
        
        finally:
            # Stop the thread monitor
            self.thread_monitor.stop_monitoring()
            
            # Close progress bar if it exists
            if not self.verbose and pbar:
                pbar.close()
            
            if self.interrupted:
                if self.verbose:
                    logging.info("URL caching interrupted")
                else:
                    print("\nURL caching interrupted")
            elif self.verbose:
                logging.info(f"Completed caching {processed_count} of {total_urls} URLs")
            else:
                print(f"Completed caching {processed_count} of {total_urls} URLs")

class ReportGenerator:
    def __init__(self, config):
        self.config = config
        self.output_dir = config.output_dir
        self.verbose = config.verbose
        
    def write_csv_report(self, filename, data, headers=None):
        """Write data to a CSV file."""
        if headers is None:
            headers = ["Source", "URL"]
            
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in data:
                writer.writerow(row)
                
        if self.verbose:
            logging.info(f"Wrote {len(data)} rows to {filepath}")
        return filepath
        
    def generate_comparison_reports(self, sitemap_urls, site_urls, sitemap_sources, site_sources, has_sitemap=True):
        """Generate comparison reports between sitemap and site URLs."""
        # Find differences
        in_site_not_sitemap = site_urls - sitemap_urls
        in_sitemap_not_site = sitemap_urls - site_urls if has_sitemap else set()
        
        # Prepare data for reports
        missing_from_sitemap_data = [(site_sources.get(url, self.config.start_url), url) 
                                    for url in sorted(in_site_not_sitemap)]
        
        # Write missing from sitemap report
        self.write_csv_report("missing_from_sitemap.csv", missing_from_sitemap_data)
        
        if has_sitemap:
            # Prepare data for missing from site report
            missing_from_site_data = [(sitemap_sources.get(url, self.config.sitemap_url), url) 
                                     for url in sorted(in_sitemap_not_site)]
            
            # Write missing from site report
            self.write_csv_report("missing_from_site.csv", missing_from_site_data)
            
            # Write all sitemap URLs report
            all_sitemap_data = [(sitemap_sources.get(url, self.config.sitemap_url), url) 
                               for url in sorted(sitemap_urls)]
            self.write_csv_report("all_sitemap_urls.csv", all_sitemap_data)
        else:
            # Create empty files for consistency
            self.write_csv_report("missing_from_site.csv", [["No sitemap found", ""]])
            self.write_csv_report("all_sitemap_urls.csv", [["No sitemap found", ""]])
        
        # Write all site URLs report
        all_site_data = [(site_sources.get(url, self.config.start_url), url) 
                         for url in sorted(site_urls)]
        self.write_csv_report("all_site_urls.csv", all_site_data)
        
        return in_site_not_sitemap, in_sitemap_not_site


class ComparisonAnalyzer:
    def __init__(self, config, report_generator):
        self.config = config
        self.report_generator = report_generator
        self.output_dir = config.output_dir
        self.verbose = config.verbose
        
    def find_previous_scan(self):
        """Find the most recent previous scan directory for the given domain."""
        domain = self.config.domain
        current_dir = self.output_dir
        
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
        
    def compare_csv_files(self, current_file, previous_file, output_file):
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
        
        # Prepare data for report
        comparison_data = []
        for url in sorted(new_issues):
            comparison_data.append(["New", url])
            
        for url in sorted(fixed_issues):
            comparison_data.append(["Fixed", url])
        
        # Write comparison results
        self.report_generator.write_csv_report(os.path.basename(output_file), comparison_data, ["Status", "URL"])
        
        if self.verbose:
            logging.info(f"Comparison found {len(new_issues)} new issues and {len(fixed_issues)} fixed issues")
        else:
            print(f"Comparison found {len(new_issues)} new issues and {len(fixed_issues)} fixed issues")
        
        return len(new_issues), len(fixed_issues)
        
    def compare_with_previous(self):
        """Compare current scan with previous scan."""
        previous_dir = self.find_previous_scan()
        
        if not previous_dir:
            if self.verbose:
                logging.warning("No previous scan found for comparison")
            else:
                print("\nNo previous scan found for comparison")
            return False
            
        if self.verbose:
            logging.info(f"Comparing with previous scan: {previous_dir}")
        else:
            print(f"\nComparing with previous scan: {os.path.basename(previous_dir)}")
        
        # Compare missing from site
        current_missing_site = os.path.join(self.output_dir, "missing_from_site.csv")
        previous_missing_site = os.path.join(previous_dir, "missing_from_site.csv")
        comparison_missing_site = os.path.join(self.output_dir, "comparison_missing_from_site.csv")
        
        new_missing_site, fixed_missing_site = self.compare_csv_files(
            current_missing_site, previous_missing_site, comparison_missing_site)
        
        # Compare missing from sitemap
        current_missing_sitemap = os.path.join(self.output_dir, "missing_from_sitemap.csv")
        previous_missing_sitemap = os.path.join(previous_dir, "missing_from_sitemap.csv")
        comparison_missing_sitemap = os.path.join(self.output_dir, "comparison_missing_from_sitemap.csv")
        
        new_missing_sitemap, fixed_missing_sitemap = self.compare_csv_files(
            current_missing_sitemap, previous_missing_sitemap, comparison_missing_sitemap)
        
        if self.verbose:
            logging.info("Comparison with previous scan complete")
        else:
            print("\nComparison with previous scan complete")
            print(f"Missing from site: {new_missing_site} new, {fixed_missing_site} fixed")
            print(f"Missing from sitemap: {new_missing_sitemap} new, {fixed_missing_sitemap} fixed")
            
        return True

class SitemapComparison:
    def __init__(self, args):
        # Initialize configuration
        self.config = Config(args)
        
        # Create output directory
        os.makedirs(self.config.output_dir, exist_ok=True)
        
        # Set up logging
        if self.config.verbose:
            logging.info(f"Created output directory: {self.config.output_dir}")
            
        # Initialize components
        self.cache_manager = CacheManager(self.config)
        self.url_processor = UrlProcessor(self.config)
        self.sitemap_fetcher = SitemapFetcher(self.config, self.cache_manager, self.url_processor)
        self.website_spider = WebsiteSpider(self.config, self.cache_manager, self.url_processor)
        self.report_generator = ReportGenerator(self.config)
        self.comparison_analyzer = ComparisonAnalyzer(self.config, self.report_generator)
        
        # Set up signal handler
        self.interrupted = False
        signal.signal(signal.SIGINT, self.signal_handler)
        
    def signal_handler(self, sig, frame):
        """Handle interrupt signal."""
        logging.info("Ctrl+C detected. Shutting down gracefully...")
        self.interrupted = True
        self.website_spider.set_interrupted()

    def run(self):
        """Run the sitemap comparison process."""
        try:
            # Get sitemap URL (discover if not provided)
            sitemap_url = self.config.sitemap_url
            sitemap_urls = set()
            sitemap_sources = {}
            
            if not sitemap_url:
                sitemap_url = self.sitemap_fetcher.discover_sitemap_url()
                self.config.sitemap_url = sitemap_url
                
            if not sitemap_url:
                if self.config.verbose:
                    logging.warning("Could not discover sitemap. Continuing with site spider only.")
                else:
                    print("No sitemap found. Continuing with site spider only.")
                # Set an empty set for sitemap URLs
                sitemap_urls_raw = set()
                has_sitemap = False
            else:
                # Get URLs from sitemap
                if not self.config.verbose:
                    print("Extracting URLs from sitemap...")
                sitemap_urls_raw, sitemap_sources = self.sitemap_fetcher.get_sitemap_urls(sitemap_url)
                has_sitemap = True
            
            # Filter and normalize sitemap URLs
            normalized_sitemap_urls = set()
            normalized_sitemap_sources = {}
            
            for url in sitemap_urls_raw:
                if self.url_processor.is_valid_url(url):
                    normalized_url = self.url_processor.normalize_url(url)
                    normalized_sitemap_urls.add(normalized_url)
                    normalized_sitemap_sources[normalized_url] = sitemap_sources.get(url, sitemap_url if sitemap_url else self.config.start_url)
            
            if has_sitemap:
                if self.config.verbose:
                    logging.info(f"After filtering and normalization, found {len(normalized_sitemap_urls)} valid URLs in sitemap")
                else:
                    print(f"Found {len(normalized_sitemap_urls)} valid URLs in sitemap")
            
            # Get URLs from spidering
            site_urls_raw, site_sources = self.website_spider.spider_website()
            
            # Check if we were interrupted
            if self.interrupted:
                logging.info("Process was interrupted. Exiting...")
                return
            
            # Filter and normalize site URLs
            normalized_site_urls = set()
            normalized_site_sources = {}
            
            for url in site_urls_raw:
                if self.url_processor.is_valid_url(url):
                    normalized_url = self.url_processor.normalize_url(url)
                    normalized_site_urls.add(normalized_url)
                    normalized_site_sources[normalized_url] = site_sources.get(url, self.config.start_url)
                    
            if self.config.verbose:
                logging.info(f"After filtering and normalization, found {len(normalized_site_urls)} valid URLs from spidering")
            else:
                print(f"Found {len(normalized_site_urls)} valid URLs from spidering")
            
            # Apply additional filtering based on configuration
            filtered_site_urls = normalized_site_urls.copy()
            
            # Apply pagination filtering if requested
            if self.config.ignore_pagination:
                before_count = len(filtered_site_urls)
                filtered_site_urls = {url for url in filtered_site_urls if not self.url_processor.is_pagination_url(url)}
                pagination_filtered = before_count - len(filtered_site_urls)
                
                if self.config.verbose:
                    logging.info(f"Filtered out {pagination_filtered} pagination URLs")
                else:
                    print(f"Ignored {pagination_filtered} pagination URLs")
    
            # Apply category and tag filtering if requested
            if self.config.ignore_categories_tags:
                before_count = len(filtered_site_urls)
                filtered_site_urls = {url for url in filtered_site_urls if not self.url_processor.is_category_or_tag_url(url)}
                category_tag_filtered = before_count - len(filtered_site_urls)
                
                if self.config.verbose:
                    logging.info(f"Filtered out {category_tag_filtered} WordPress category and tag URLs")
                else:
                    print(f"Ignored {category_tag_filtered} WordPress category and tag URLs")
            
            # Generate comparison reports
            in_site_not_sitemap, in_sitemap_not_site = self.report_generator.generate_comparison_reports(
                normalized_sitemap_urls, filtered_site_urls, 
                normalized_sitemap_sources, normalized_site_sources,
                has_sitemap)
                
            # Print summary
            if not self.config.verbose:
                print(f"Found {len(in_site_not_sitemap)} URLs missing from sitemap")
                if has_sitemap:
                    print(f"Found {len(in_sitemap_not_site)} URLs missing from site")
            
            # Cache pages that are in sitemap but not found by site spider
            if has_sitemap and in_sitemap_not_site:
                self.website_spider.cache_missing_urls(in_sitemap_not_site)
            
            # Compare with previous scan if requested
            if self.config.compare_previous:
                self.comparison_analyzer.compare_with_previous()
            
            # Compress output files
            self.cache_manager.compress_output_files()
            
            if self.config.verbose:
                logging.info("Comparison complete!")
            else:
                print("\nComparison complete!")
                print(f"Results saved to: {self.config.output_dir}")
                
        except Exception as e:
            logging.error(f"Error in main process: {e}")
            if self.config.verbose:
                import traceback
                logging.error(traceback.format_exc())
            return 1
        finally:
            if self.interrupted:
                if self.config.verbose:
                    logging.info("Process interrupted by user. Exiting...")
                else:
                    print("\nProcess interrupted by user. Exiting...")
                return 0
        return 0

# Main function
def main():
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
    parser.add_argument('--thread-timeout', type=int, default=30, 
                        help='Maximum time in seconds a thread can spend on a single URL (default: 30)')
    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, 
                        format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create and run the sitemap comparison
    comparison = SitemapComparison(args)
    return comparison.run()

if __name__ == "__main__":
    sys.exit(main())
