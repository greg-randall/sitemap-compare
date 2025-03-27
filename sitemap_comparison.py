import argparse
import re
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET
from curl_cffi import requests
from bs4 import BeautifulSoup
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up argument parser
parser = argparse.ArgumentParser(description='Compare sitemap URLs with URLs found by spidering a website')
parser.add_argument('start_url', help='The URL to start spidering from')
parser.add_argument('sitemap_url', help='The URL of the sitemap')
parser.add_argument('--output-prefix', default='comparison_results', help='Prefix for output files')
args = parser.parse_args()

def get_sitemap_urls(sitemap_url):
    """Extract all URLs from a sitemap."""
    logging.info(f"Fetching sitemap from {sitemap_url}")
    try:
        response = requests.get(sitemap_url)
        response.raise_for_status()
        
        # Check if this is a sitemap index
        root = ET.fromstring(response.text)
        
        # Namespace handling
        ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        urls = set()
        
        # Check if this is a sitemap index
        sitemaps = root.findall('.//sm:sitemap/sm:loc', ns)
        if sitemaps:
            logging.info(f"Found sitemap index with {len(sitemaps)} sitemaps")
            for sitemap in sitemaps:
                sub_urls = get_sitemap_urls(sitemap.text)
                urls.update(sub_urls)
        else:
            # Regular sitemap
            for url in root.findall('.//sm:url/sm:loc', ns):
                urls.add(url.text)
            
        logging.info(f"Found {len(urls)} URLs in sitemap")
        return urls
    except Exception as e:
        logging.error(f"Error fetching sitemap: {e}")
        return set()

def normalize_url(url):
    """Normalize URL to avoid duplicates due to trivial differences."""
    parsed = urlparse(url)
    # Remove trailing slash if present
    path = parsed.path
    if path.endswith('/') and path != '/':
        path = path[:-1]
    # Reconstruct URL without query parameters and fragments
    return f"{parsed.scheme}://{parsed.netloc}{path}"

def spider_website(start_url, max_pages=10000):
    """Spider a website and return all discovered URLs."""
    base_domain = urlparse(start_url).netloc
    visited_urls = set()
    to_visit = {start_url}
    found_urls = set()
    
    logging.info(f"Starting to spider {start_url}")
    
    while to_visit and len(visited_urls) < max_pages:
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
    
    logging.info(f"Spidering complete. Found {len(found_urls)} URLs")
    return found_urls

def main():
    # Get URLs from sitemap
    sitemap_urls = get_sitemap_urls(args.sitemap_url)
    
    # Get URLs from spidering
    site_urls = spider_website(args.start_url)
    
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

if __name__ == "__main__":
    main()
