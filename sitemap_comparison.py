import argparse
import re
import signal
import sys
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET
from curl_cffi import requests
from bs4 import BeautifulSoup
import logging
import html

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up argument parser
parser = argparse.ArgumentParser(description='Compare sitemap URLs with URLs found by spidering a website')
parser.add_argument('start_url', help='The URL to start spidering from')
parser.add_argument('--sitemap-url', help='The URL of the sitemap (optional, will try to discover if not provided)')
parser.add_argument('--output-prefix', default='comparison_results', help='Prefix for output files')
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
    # Match both absolute URLs and relative URLs
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
    
    try:
        response = requests.get(sitemap_url, timeout=10)
        response.raise_for_status()
        content = response.text
        
        # First try XML parsing for standard sitemaps
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
    # Reconstruct URL without query parameters and fragments
    return f"{parsed.scheme}://{parsed.netloc}{path}"

def is_valid_url(url):
    """Check if a URL is valid and should be included in results."""
    if not url:
        return False
        
    # Skip URLs with common non-content extensions
    skip_extensions = ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.ttf']
    for ext in skip_extensions:
        if url.lower().endswith(ext):
            return False
            
    # Skip URLs with common query parameters that indicate non-content
    if any(param in url for param in ['?replytocom=', '?share=', '?like=']):
        return False
        
    return True

def spider_website(start_url, max_pages=10000):
    """Spider a website and return all discovered URLs."""
    global interrupted
    base_domain = urlparse(start_url).netloc
    visited_urls = set()
    to_visit = {start_url}
    found_urls = set()
    
    logging.info(f"Starting to spider {start_url}")
    
    try:
        while to_visit and len(visited_urls) < max_pages and not interrupted:
            current_url = to_visit.pop()
            
            if current_url in visited_urls:
                continue
                
            logging.info(f"Visiting {current_url} ({len(visited_urls)}/{max_pages})")
            
            try:
                response = requests.get(current_url, timeout=10)
                visited_urls.add(current_url)
                found_urls.add(current_url)
                
                if 'text/html' not in response.headers.get('Content-Type', ''):
                    continue
                    
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find all links
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
                    
                    if clean_url not in visited_urls:
                        to_visit.add(clean_url)
                        
            except Exception as e:
                logging.error(f"Error visiting {current_url}: {e}")
    except Exception as e:
        logging.error(f"Spidering error: {e}")
        
    if interrupted:
        logging.info("Spidering interrupted. Returning URLs found so far...")
    
    logging.info(f"Spidering complete. Found {len(found_urls)} URLs")
    return found_urls

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
        
        # Get URLs from sitemap
        sitemap_urls_raw = get_sitemap_urls(sitemap_url)
        
        # Filter and normalize sitemap URLs
        sitemap_urls = set()
        for url in sitemap_urls_raw:
            if is_valid_url(url):
                sitemap_urls.add(normalize_url(url))
        
        logging.info(f"After filtering and normalization, found {len(sitemap_urls)} valid URLs in sitemap")
        
        # Get URLs from spidering
        site_urls_raw = spider_website(args.start_url)
        
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
        
        # Write results to files
        missing_from_sitemap_file = f"{args.output_prefix}_missing_from_sitemap.txt"
        with open(missing_from_sitemap_file, 'w') as f:
            for url in sorted(in_site_not_sitemap):
                f.write(f"{url}\n")
        logging.info(f"Wrote {len(in_site_not_sitemap)} URLs missing from sitemap to {missing_from_sitemap_file}")
        
        missing_from_site_file = f"{args.output_prefix}_missing_from_site.txt"
        with open(missing_from_site_file, 'w') as f:
            for url in sorted(in_sitemap_not_site):
                f.write(f"{url}\n")
        logging.info(f"Wrote {len(in_sitemap_not_site)} URLs missing from site to {missing_from_site_file}")
        
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
