import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import tempfile
import queue
import threading
from io import StringIO
import csv
from urllib.parse import urlparse

# Import the functions to test
from sitemap_comparison import (
    discover_sitemap_url,
    extract_urls_with_regex,
    normalize_url,
    is_valid_url,
    get_sitemap_urls,
    spider_website,
    url_to_filename,
    find_previous_scan,
    compare_csv_files
)

class TestSitemapComparison(unittest.TestCase):
    
    def setUp(self):
        # Create a temporary directory for test outputs
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, "cache-xml"), exist_ok=True)
        
    def tearDown(self):
        # Clean up temporary directory
        import shutil
        shutil.rmtree(self.test_dir)
    
    @patch('sitemap_comparison.requests.get')
    @patch('sitemap_comparison.logging.error')  # Add this to suppress the error log
    @patch('sitemap_comparison.logging.info')   # Add this to suppress info logs
    def test_discover_sitemap_url(self, mock_info, mock_error, mock_get):
        # Mock response for robots.txt with sitemap
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "User-agent: *\nDisallow: /admin\nSitemap: https://example.com/sitemap.xml"
        mock_get.return_value = mock_response
    
        # Test discovery from robots.txt
        result = discover_sitemap_url("https://example.com", self.test_dir, True)
        self.assertEqual(result, "https://example.com/sitemap.xml")
    
        # Mock response for robots.txt without sitemap
        mock_response.text = "User-agent: *\nDisallow: /admin"
    
        # Mock response for common sitemap locations
        def side_effect(url, timeout=10):
            if url == "https://example.com/robots.txt":
                response = MagicMock()
                response.status_code = 200
                response.text = "User-agent: *\nDisallow: /admin"
                return response
            elif url == "https://example.com/sitemap.xml":
                response = MagicMock()
                response.status_code = 200
                response.text = "<urlset><url><loc>https://example.com/page1</loc></url></urlset>"
                return response
            else:
                response = MagicMock()
                response.status_code = 404
                return response
            
        mock_get.side_effect = side_effect
    
        # Test discovery from common locations
        result = discover_sitemap_url("https://example.com", self.test_dir, True)
        self.assertEqual(result, "https://example.com/sitemap.xml")
    
        # Test when no sitemap is found
        mock_get.side_effect = lambda url, timeout=10: MagicMock(status_code=404)
        result = discover_sitemap_url("https://example.com", self.test_dir, True)
        self.assertIsNone(result)
    
        # Verify that the error was logged
        mock_error.assert_called_with("Could not automatically discover sitemap")
    
    def test_extract_urls_with_regex(self):
        # Test extracting URLs from sitemap XML
        content = """
        <urlset>
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>
        """
        result = extract_urls_with_regex(content, "https://example.com")
        self.assertEqual(result, {"https://example.com/page1", "https://example.com/page2"})
        
        # Test extracting URLs from HTML - the function only extracts absolute URLs
        # Our implementation doesn't convert relative URLs in this function
        content = """
        <html>
            <body>
                <a href="https://example.com/page1">Link 1</a>
                <a href="https://example.com/page2">Link 2</a>
                <a href="https://example.com/page3">Link 3</a>
            </body>
        </html>
        """
        result = extract_urls_with_regex(content, "https://example.com")
        self.assertEqual(result, {"https://example.com/page1", "https://example.com/page2", "https://example.com/page3"})
    
    def test_normalize_url(self):
        # Test URL normalization
        self.assertEqual(normalize_url("https://Example.com/page/"), "https://example.com/page")
        self.assertEqual(normalize_url("https://example.com"), "https://example.com/")
        self.assertEqual(normalize_url("https://example.com/page?query=value#fragment"), "https://example.com/page")
        self.assertEqual(normalize_url("https://example.com/page/"), "https://example.com/page")
    
    def test_is_valid_url(self):
        # Test valid URLs
        self.assertTrue(is_valid_url("https://example.com/page"))
        self.assertTrue(is_valid_url("https://example.com/"))
        
        # Test invalid URLs
        self.assertFalse(is_valid_url(""))
        self.assertFalse(is_valid_url("https://example.com/image.jpg"))
        self.assertFalse(is_valid_url("https://example.com/document.pdf"))
        self.assertFalse(is_valid_url("https://example.com/style.css"))
        self.assertFalse(is_valid_url("https://example.com/script.js"))
        self.assertFalse(is_valid_url("https://example.com/page?replytocom=123"))
    
    def test_url_to_filename(self):
        # Test URL to filename conversion
        self.assertEqual(url_to_filename("https://example.com/page"), "https_--example.com-page")
        self.assertEqual(url_to_filename("https://example.com/page?query=value&param=123"), 
                         "https_--example.com-page_query_value_param_123")
        self.assertEqual(url_to_filename("https://example.com/page#fragment"), 
                         "https_--example.com-page_fragment")
    
    @patch('sitemap_comparison.requests.get')
    @patch('sitemap_comparison.logging.error')  # Suppress error logs
    @patch('sitemap_comparison.logging.info')   # Suppress info logs
    def test_get_sitemap_urls(self, mock_info, mock_error, mock_get):
        # Test 1: Simple sitemap
        simple_response = MagicMock()
        simple_response.status_code = 200
        simple_response.text = """
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>
        """
        
        # Configure the mock to return the simple sitemap response
        mock_get.return_value = simple_response
        
        # Test simple sitemap
        urls, sources = get_sitemap_urls("https://example.com/sitemap.xml", self.test_dir, True)
        self.assertEqual(urls, {"https://example.com/page1", "https://example.com/page2"})
        self.assertEqual(sources["https://example.com/page1"], "https://example.com/sitemap.xml")
        self.assertEqual(sources["https://example.com/page2"], "https://example.com/sitemap.xml")
        
        # Test 2: Sitemap index with sub-sitemaps
        # Reset the mock to use side_effect instead of return_value
        mock_get.reset_mock()
        
        # Define responses for different URLs
        def side_effect(url, timeout=10):
            if url == "https://example.com/sitemap.xml":
                response = MagicMock()
                response.status_code = 200
                response.text = """
                <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                    <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
                    <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
                </sitemapindex>
                """
                return response
            elif url == "https://example.com/sitemap1.xml":
                response = MagicMock()
                response.status_code = 200
                response.text = """
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                    <url><loc>https://example.com/page1</loc></url>
                </urlset>
                """
                return response
            elif url == "https://example.com/sitemap2.xml":
                response = MagicMock()
                response.status_code = 200
                response.text = """
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                    <url><loc>https://example.com/page2</loc></url>
                </urlset>
                """
                return response
            else:
                response = MagicMock()
                response.status_code = 404
                return response
                
        # Set the side_effect for the mock
        mock_get.side_effect = side_effect
        
        # Test sitemap index
        urls, sources = get_sitemap_urls("https://example.com/sitemap.xml", self.test_dir, True)
        self.assertEqual(urls, {"https://example.com/page1", "https://example.com/page2"})
        self.assertEqual(sources["https://example.com/page1"], "https://example.com/sitemap1.xml")
        self.assertEqual(sources["https://example.com/page2"], "https://example.com/sitemap2.xml")
    
    @patch('sitemap_comparison.requests.get')
    @patch('sitemap_comparison.logging.error')  # Suppress error logs
    @patch('sitemap_comparison.logging.info')   # Suppress info logs
    @patch('sitemap_comparison.logging.warning')  # Suppress warning logs
    def test_spider_website(self, mock_warning, mock_info, mock_error, mock_get):
        # Mock responses for spidering
        def side_effect(url, timeout=10):
            if url == "https://example.com":
                response = MagicMock()
                response.status_code = 200
                response.headers = {"Content-Type": "text/html"}
                response.text = """
                <html>
                    <body>
                        <a href="https://example.com/page1">Link 1</a>
                        <a href="/page2">Link 2</a>
                        <a href="https://external.com">External Link</a>
                    </body>
                </html>
                """
                return response
            elif url == "https://example.com/page1":
                response = MagicMock()
                response.status_code = 200
                response.headers = {"Content-Type": "text/html"}
                response.text = """
                <html>
                    <body>
                        <a href="https://example.com/page3">Link 3</a>
                    </body>
                </html>
                """
                return response
            elif url == "https://example.com/page2":
                response = MagicMock()
                response.status_code = 200
                response.headers = {"Content-Type": "text/html"}
                response.text = """
                <html>
                    <body>
                        <a href="https://example.com/page4">Link 4</a>
                    </body>
                </html>
                """
                return response
            elif url in ["https://example.com/page3", "https://example.com/page4"]:
                response = MagicMock()
                response.status_code = 200
                response.headers = {"Content-Type": "text/html"}
                response.text = "<html><body>Content</body></html>"
                return response
            else:
                response = MagicMock()
                response.status_code = 404
                return response
                
        mock_get.side_effect = side_effect
        
        # Test spidering
        urls, sources = spider_website("https://example.com", max_pages=10, num_workers=1, output_dir=self.test_dir, verbose=True)
        
        # Check that all expected URLs were found
        expected_urls = {
            "https://example.com", 
            "https://example.com/page1", 
            "https://example.com/page2",
            "https://example.com/page3",
            "https://example.com/page4"
        }
        self.assertEqual(urls, expected_urls)
        
        # Check sources
        self.assertEqual(sources["https://example.com"], "https://example.com")  # Start URL is its own source
        self.assertEqual(sources["https://example.com/page1"], "https://example.com")
        self.assertEqual(sources["https://example.com/page2"], "https://example.com")
        self.assertEqual(sources["https://example.com/page3"], "https://example.com/page1")
        self.assertEqual(sources["https://example.com/page4"], "https://example.com/page2")
    
    @patch('sitemap_comparison.requests.get')
    @patch('sitemap_comparison.logging.error')  # Suppress error logs
    @patch('sitemap_comparison.logging.info')   # Suppress info logs
    def test_compare_csv_files(self, mock_info, mock_error, mock_get):
        # Create temporary CSV files for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create current CSV
            current_file = os.path.join(temp_dir, "current.csv")
            with open(current_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "URL"])
                writer.writerow(["https://example.com", "https://example.com/page1"])
                writer.writerow(["https://example.com", "https://example.com/page2"])
                writer.writerow(["https://example.com", "https://example.com/page3"])
            
            # Create previous CSV
            previous_file = os.path.join(temp_dir, "previous.csv")
            with open(previous_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "URL"])
                writer.writerow(["https://example.com", "https://example.com/page1"])
                writer.writerow(["https://example.com", "https://example.com/page4"])
            
            # Create output file
            output_file = os.path.join(temp_dir, "comparison.csv")
            
            # Compare files
            new_issues, fixed_issues = compare_csv_files(current_file, previous_file, output_file, True)
            
            # Check results
            self.assertEqual(new_issues, 2)  # page2 and page3 are new
            self.assertEqual(fixed_issues, 1)  # page4 is fixed
            
            # Check output file content
            with open(output_file, 'r', newline='') as f:
                reader = csv.reader(f)
                rows = list(reader)
                
                self.assertEqual(rows[0], ["Status", "URL"])
                self.assertEqual(rows[1], ["New", "https://example.com/page2"])
                self.assertEqual(rows[2], ["New", "https://example.com/page3"])
                self.assertEqual(rows[3], ["Fixed", "https://example.com/page4"])
    
    @patch('sitemap_comparison.os.path.exists')
    @patch('sitemap_comparison.os.path.isdir')
    @patch('sitemap_comparison.os.listdir')
    @patch('sitemap_comparison.os.path.getmtime')
    def test_find_previous_scan(self, mock_getmtime, mock_listdir, mock_isdir, mock_exists):
        # Mock directory structure
        mock_listdir.return_value = ["scan1", "scan2", "scan3"]
        mock_isdir.return_value = True
        
        # Mock file existence checks
        def exists_side_effect(path):
            return "scan2" in path or "scan3" in path
        mock_exists.side_effect = exists_side_effect
        
        # Mock modification times
        def getmtime_side_effect(path):
            if "scan2" in path:
                return 1000  # older
            elif "scan3" in path:
                return 2000  # newer
            return 0
        mock_getmtime.side_effect = getmtime_side_effect
        
        # Test finding the most recent scan
        result = find_previous_scan("/current/path", "example.com")
        self.assertEqual(result, os.path.join("sites", "example.com", "scan3"))
        
        # Test when no previous scans exist
        mock_exists.side_effect = lambda path: False
        result = find_previous_scan("/current/path", "example.com")
        self.assertIsNone(result)
    
    def test_csv_output_format(self, mock_info, mock_error, mock_get):
        # Create a temporary directory for output
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock sitemap URLs
            sitemap_urls = {"https://example.com/page1", "https://example.com/page2", "https://example.com/page3"}
            sitemap_sources = {
                "https://example.com/page1": "https://example.com/sitemap.xml",
                "https://example.com/page2": "https://example.com/sitemap.xml",
                "https://example.com/page3": "https://example.com/sitemap.xml"
            }
            
            # Mock site URLs
            site_urls = {"https://example.com/page1", "https://example.com/page2", "https://example.com/page4"}
            site_sources = {
                "https://example.com/page1": "https://example.com",
                "https://example.com/page2": "https://example.com/page1",
                "https://example.com/page4": "https://example.com/page2"
            }
            
            # Create CSV files
            missing_from_sitemap_file = os.path.join(temp_dir, "missing_from_sitemap.csv")
            with open(missing_from_sitemap_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "URL"])
                for url in sorted(site_urls - sitemap_urls):
                    writer.writerow([site_sources.get(url, "https://example.com"), url])
            
            missing_from_site_file = os.path.join(temp_dir, "missing_from_site.csv")
            with open(missing_from_site_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "URL"])
                for url in sorted(sitemap_urls - site_urls):
                    writer.writerow([sitemap_sources.get(url, "https://example.com/sitemap.xml"), url])
            
            # Check CSV file contents
            with open(missing_from_sitemap_file, 'r', newline='') as f:
                reader = csv.reader(f)
                rows = list(reader)
                self.assertEqual(rows[0], ["Source", "URL"])
                self.assertEqual(rows[1], ["https://example.com/page2", "https://example.com/page4"])
            
            with open(missing_from_site_file, 'r', newline='') as f:
                reader = csv.reader(f)
                rows = list(reader)
                self.assertEqual(rows[0], ["Source", "URL"])
                self.assertEqual(rows[1], ["https://example.com/sitemap.xml", "https://example.com/page3"])

if __name__ == '__main__':
    unittest.main()
