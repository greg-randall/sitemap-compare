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

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up argument parser
parser = argparse.ArgumentParser(description='Compare sitemap URLs with URLs found by spidering a website')
parser.add_argument('start_url', help='The URL to start spidering from')
parser.add_argument('--sitemap-url', help='The URL of the sitemap (optional, will try to discover if not provided)')
parser.add_argument('--output-prefix', default='comparison_results', help='Prefix for output files')
parser.add_argument('--workers', type=int, default=4, help='Number of parallel workers for spidering (default: 4)')
parser.add_argument('--max-pages', type=int, default=10000, help='Maximum number of pages to spider (default: 10000)')
args = parser.parse_args()

# Global flag to track interruption
interrupted = False

# Define signal handler for graceful exit
def signal_handler(sig, frame):
    global interrupted
    logging.info("Ctrl+C detected. Shutting down gracefully...")
    interrupted = True

# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)

def discover_sitemap_url(base_url):
    """Try to automatically discover the sitemap URL."""
    logging.info(f"Attempting to discover sitemap for {base_url}")
    
    # Parse the base URL to get the domain
    parsed_url = urlparse(base_url)
    base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
    
    # Common sitemap locations to check
    potential_locations = [
        f"{base_domain}/sitemap.xml",
        f"{base_domain}/sitemap_index.xml",
        f"{base_domain}/sitemap.php",
        f"{base_domain}/sitemap.txt",
    ]
    
    # Check robots.txt first (most reliable method)
    try:
        robots_url = f"{base_domain}/robots.txt"
        logging.info(f"Checking robots.txt at {robots_url}")
        response = requests.get(robots_url, timeout=10)
        
        if response.status_code == 200:
            # Look for Sitemap: directive in robots.txt
            for line in response.text.splitlines():
                if line.lower().startswith('sitemap:'):
                    sitemap_url = line.split(':', 1)[1].strip()
                    logging.info(f"Found sitemap in robots.txt: {sitemap_url}")
                    return sitemap_url
    except Exception as e:
        logging.warning(f"Error checking robots.txt: {e}")
    
    # Try common locations
    for url in potential_locations:
        try:
            logging.info(f"Checking potential sitemap at {url}")
            response = requests.get(url, timeout=10)
            if response.status_code == 200 and ('<urlset' in response.text or '<sitemapindex' in response.text):
                logging.info(f"Found sitemap at {url}")
                return url
        except Exception as e:
            logging.warning(f"Error checking {url}: {e}")
    
    logging.error("Could not automatically discover sitemap")
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

def get_sitemap_urls(sitemap_url):
    """Extract all URLs from a sitemap, handling different formats and recursion."""
    logging.info(f"Fetching sitemap from {sitemap_url}")
    urls = set()
    content = ""
    
    try:
        response = requests.get(sitemap_url, timeout=10)
        response.raise_for_status()
        content = response.text
        
        # Try direct regex extraction of <loc> tags first (most reliable for malformed XML)
        loc_urls = extract_urls_with_regex(content, sitemap_url)
        if loc_urls:
            logging.info(f"Found {len(loc_urls)} URLs using direct <loc> tag extraction")
            
            # Check if any of these are sitemaps themselves
            sitemap_urls = [url for url in loc_urls if 'sitemap' in url.lower() and url.endswith(('.xml', '.xml.gz'))]
            if sitemap_urls:
                logging.info(f"Found {len(sitemap_urls)} sub-sitemaps to process")
                for sub_sitemap_url in sitemap_urls:
                    sub_urls = get_sitemap_urls(sub_sitemap_url)
                    urls.update(sub_urls)
                    
                # Remove the sitemap URLs from the regular URLs
                regular_urls = loc_urls - set(sitemap_urls)
                urls.update(regular_urls)
            else:
                urls.update(loc_urls)
                
            if urls:
                logging.info(f"Successfully extracted URLs from sitemap, found {len(urls)} URLs")
                return urls
        
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
                    logging.info(f"Found sitemap index with {len(sitemaps)} sitemaps")
                    for sitemap in sitemaps:
                        sub_sitemap_url = sitemap.text.strip()
                        sub_urls = get_sitemap_urls(sub_sitemap_url)
                        urls.update(sub_urls)
                else:
                    # Regular sitemap
                    url_elements = (root.findall('.//sm:url/sm:loc', namespaces) or 
                                   root.findall('.//url/loc', {}))
                    
                    for url_element in url_elements:
                        urls.add(url_element.text.strip())
                        
                if urls:
                    logging.info(f"Successfully parsed XML sitemap, found {len(urls)} URLs")
                    return urls
            except ET.ParseError as e:
                logging.error(f"XML parsing error in sitemap {sitemap_url}: {e}")
        
        # If XML parsing failed or it's not an XML sitemap, try HTML parsing
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
                    logging.info(f"Found sitemap link in HTML: {href}")
                    sub_urls = get_sitemap_urls(href)
                    urls.update(sub_urls)
                else:
                    # Parse the URL to check if it's from the same domain
                    parsed_href = urlparse(href)
                    parsed_sitemap = urlparse(sitemap_url)
                    
                    if parsed_href.netloc == parsed_sitemap.netloc:
                        urls.add(href)
        except Exception as e:
            logging.error(f"BeautifulSoup parsing error: {e}")
        
        # Check if it's a text sitemap (one URL per line)
        if not urls and all(line.startswith(('http://', 'https://')) for line in content.splitlines() if line.strip()):
            for line in content.splitlines():
                line = line.strip()
                if line and line.startswith(('http://', 'https://')):
                    urls.add(line)
        
        # If still no URLs found, use regex as a last resort
        if not urls:
            logging.info("No URLs found with standard methods, trying regex extraction")
            regex_urls = extract_urls_with_regex(content, sitemap_url)
            urls.update(regex_urls)
        
        logging.info(f"Found {len(urls)} URLs in sitemap {sitemap_url}")
        return urls
    except Exception as e:
        logging.error(f"Error fetching sitemap {sitemap_url}: {e}")
        # Try regex extraction as a last resort
        try:
            logging.info("Attempting regex extraction after exception")
            regex_urls = extract_urls_with_regex(content, sitemap_url)
            urls.update(regex_urls)
            logging.info(f"Regex extraction found {len(urls)} URLs after exception")
        except Exception as regex_error:
            logging.error(f"Regex extraction also failed: {regex_error}")
        return urls

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

def spider_website(start_url, max_pages=10000, num_workers=4):
    """Spider a website and return all discovered URLs using parallel workers."""
    global interrupted
    base_domain = urlparse(start_url).netloc
    
    # Use thread-safe collections
    visited_urls = set()
    found_urls = set()
    url_queue = queue.Queue()
    url_queue.put(start_url)
    
    # Locks for thread safety
    visited_lock = threading.Lock()
    found_lock = threading.Lock()
    
    # Counter for progress reporting
    visited_count = 0
    
    logging.info(f"Starting to spider {start_url} with {num_workers} parallel workers")
    
    def process_url():
        nonlocal visited_count
        while not interrupted and visited_count < max_pages:
            try:
                # Get URL with timeout to allow for interruption
                try:
                    current_url = url_queue.get(timeout=1)
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
                
                logging.info(f"Visiting {current_url} ({visited_count}/{max_pages})")
                
                try:
                    response = requests.get(current_url, timeout=10)
                    
                    with found_lock:
                        found_urls.add(current_url)
                    
                    # Skip non-HTML content types and binary files
                    content_type = response.headers.get('Content-Type', '').lower()
                    if ('text/html' not in content_type and 
                        'application/xhtml+xml' not in content_type):
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
                    
                    # Add new URLs to the queue
                    for url in new_urls:
                        url_queue.put(url)
                        
                except Exception as e:
                    logging.error(f"Error visiting {current_url}: {e}")
                
                url_queue.task_done()
                
            except Exception as e:
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
        logging.error(f"Spidering error: {e}")
        
    if interrupted:
        logging.info("Spidering interrupted. Returning URLs found so far...")
    
    logging.info(f"Spidering complete. Found {len(found_urls)} URLs")
    return found_urls

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
    
    logging.info(f"Created output directory: {base_dir}")
    return base_dir

def main():
    global interrupted
    try:
        # Get sitemap URL (discover if not provided)
        sitemap_url = args.sitemap_url
        if not sitemap_url:
            sitemap_url = discover_sitemap_url(args.start_url)
            if not sitemap_url:
                logging.error("Could not discover sitemap. Please provide sitemap URL with --sitemap-url")
                sys.exit(1)
        
        # Create output directory
        output_dir = create_output_directory(args.start_url)
        
        # Get URLs from sitemap
        sitemap_urls_raw = get_sitemap_urls(sitemap_url)
        
        # Filter and normalize sitemap URLs
        sitemap_urls = set()
        for url in sitemap_urls_raw:
            if is_valid_url(url):
                sitemap_urls.add(normalize_url(url))
        
        logging.info(f"After filtering and normalization, found {len(sitemap_urls)} valid URLs in sitemap")
        
        # Get URLs from spidering
        site_urls_raw = spider_website(args.start_url, max_pages=args.max_pages, num_workers=args.workers)
        
        # Filter and normalize site URLs
        site_urls = set()
        for url in site_urls_raw:
            if is_valid_url(url):
                site_urls.add(normalize_url(url))
                
        logging.info(f"After filtering and normalization, found {len(site_urls)} valid URLs from spidering")
        
        # Check if we were interrupted
        if interrupted:
            logging.info("Process was interrupted. Exiting...")
            sys.exit(0)
            
        # Find differences
        in_site_not_sitemap = site_urls - sitemap_urls
        in_sitemap_not_site = sitemap_urls - site_urls
        
        # Write results to files in the output directory
        missing_from_sitemap_file = os.path.join(output_dir, "missing_from_sitemap.txt")
        with open(missing_from_sitemap_file, 'w') as f:
            for url in sorted(in_site_not_sitemap):
                f.write(f"{url}\n")
        logging.info(f"Wrote {len(in_site_not_sitemap)} URLs missing from sitemap to {missing_from_sitemap_file}")
        
        missing_from_site_file = os.path.join(output_dir, "missing_from_site.txt")
        with open(missing_from_site_file, 'w') as f:
            for url in sorted(in_sitemap_not_site):
                f.write(f"{url}\n")
        logging.info(f"Wrote {len(in_sitemap_not_site)} URLs missing from site to {missing_from_site_file}")
        
        # Write all URLs to files for reference
        all_sitemap_urls_file = os.path.join(output_dir, "all_sitemap_urls.txt")
        with open(all_sitemap_urls_file, 'w') as f:
            for url in sorted(sitemap_urls):
                f.write(f"{url}\n")
        
        all_site_urls_file = os.path.join(output_dir, "all_site_urls.txt")
        with open(all_site_urls_file, 'w') as f:
            for url in sorted(site_urls):
                f.write(f"{url}\n")
        
        logging.info("Comparison complete!")
    except Exception as e:
        logging.error(f"Error in main process: {e}")
        sys.exit(1)
    finally:
        if interrupted:
            logging.info("Process interrupted by user. Exiting...")
            sys.exit(0)

if __name__ == "__main__":
    main()
