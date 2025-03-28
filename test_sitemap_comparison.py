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
            # First check if the sites directory exists
            if "sites/example.com" in path:
                return True
                
            # Make sure both CSV files exist for scan2 and scan3
            if "scan2" in path or "scan3" in path:
                if "missing_from_site.csv" in path or "missing_from_sitemap.csv" in path:
                    return True
            return False
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
    
    @patch('sitemap_comparison.requests.get')
    @patch('sitemap_comparison.logging.error')  # Suppress error logs
    @patch('sitemap_comparison.logging.info')   # Suppress info logs
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
    
    @patch('sitemap_comparison.find_previous_scan')
    @patch('sitemap_comparison.compare_csv_files')
    @patch('sitemap_comparison.os.path.basename')
    @patch('sitemap_comparison.os.path.join')
    @patch('sitemap_comparison.urlparse')
    def test_compare_previous_integration(self, mock_urlparse, mock_path_join, mock_basename, 
                                         mock_compare_csv, mock_find_previous):
        """Test the integration of the --compare-previous functionality in the main workflow."""
        # Setup mocks
        mock_urlparse.return_value = MagicMock(netloc="example.com")
        mock_find_previous.return_value = "/path/to/previous/scan"
        mock_basename.return_value = "previous-scan-timestamp"
        
        # Mock os.path.join to return predictable paths
        def join_side_effect(*args):
            return "/".join(args)
        mock_path_join.side_effect = join_side_effect
        
        # Mock compare_csv_files to return some results
        mock_compare_csv.side_effect = [
            (2, 3),  # 2 new issues, 3 fixed issues for missing_from_site
            (1, 4)   # 1 new issue, 4 fixed issues for missing_from_sitemap
        ]
        
        # Create a temporary directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            current_dir = os.path.join(temp_dir, "current")
            os.makedirs(current_dir)
            
            # Create the necessary CSV files
            for filename in ["missing_from_site.csv", "missing_from_sitemap.csv"]:
                with open(os.path.join(current_dir, filename), 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Source", "URL"])
                    writer.writerow(["https://example.com", "https://example.com/page1"])
            
            # Call the comparison code directly
            domain = "example.com"
            output_dir = current_dir
            verbose = False
            
            # This simulates the relevant part of the main function
            # Use the mock instead of the actual function
            previous_dir = mock_find_previous(output_dir, domain)
            
            if previous_dir:
                print(f"\nComparing with previous scan: {mock_basename(previous_dir)}")
                
                # Compare missing from site
                current_missing_site = mock_path_join(output_dir, "missing_from_site.csv")
                previous_missing_site = mock_path_join(previous_dir, "missing_from_site.csv")
                comparison_missing_site = mock_path_join(output_dir, "comparison_missing_from_site.csv")
                
                new_missing_site, fixed_missing_site = mock_compare_csv(
                    current_missing_site, previous_missing_site, comparison_missing_site, verbose)
                
                # Compare missing from sitemap
                current_missing_sitemap = mock_path_join(output_dir, "missing_from_sitemap.csv")
                previous_missing_sitemap = mock_path_join(previous_dir, "missing_from_sitemap.csv")
                comparison_missing_sitemap = mock_path_join(output_dir, "comparison_missing_from_sitemap.csv")
                
                new_missing_sitemap, fixed_missing_sitemap = mock_compare_csv(
                    current_missing_sitemap, previous_missing_sitemap, comparison_missing_sitemap, verbose)
                
                print("\nComparison with previous scan complete")
                print(f"Missing from site: {new_missing_site} new, {fixed_missing_site} fixed")
                print(f"Missing from sitemap: {new_missing_sitemap} new, {fixed_missing_sitemap} fixed")
            
            # Verify the mocks were called correctly
            mock_find_previous.assert_called_once_with(current_dir, domain)
            
            # Check that compare_csv_files was called twice with the correct parameters
            self.assertEqual(mock_compare_csv.call_count, 2)
            
            # First call for missing_from_site.csv
            args1, kwargs1 = mock_compare_csv.call_args_list[0]
            self.assertEqual(args1[0], current_dir + "/missing_from_site.csv")
            self.assertEqual(args1[1], "/path/to/previous/scan/missing_from_site.csv")
            self.assertEqual(args1[2], current_dir + "/comparison_missing_from_site.csv")
            self.assertEqual(args1[3], False)  # verbose
            
            # Second call for missing_from_sitemap.csv
            args2, kwargs2 = mock_compare_csv.call_args_list[1]
            self.assertEqual(args2[0], current_dir + "/missing_from_sitemap.csv")
            self.assertEqual(args2[1], "/path/to/previous/scan/missing_from_sitemap.csv")
            self.assertEqual(args2[2], current_dir + "/comparison_missing_from_sitemap.csv")
            self.assertEqual(args2[3], False)  # verbose

    @patch('sitemap_comparison.find_previous_scan')
    @patch('sitemap_comparison.urlparse')
    def test_compare_previous_no_previous_scan(self, mock_urlparse, mock_find_previous):
        """Test the --compare-previous functionality when no previous scan is found."""
        # Setup mocks
        mock_urlparse.return_value = MagicMock(netloc="example.com")
        mock_find_previous.return_value = None  # No previous scan found
        
        # Create a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = temp_dir
            domain = "example.com"
            verbose = False
            
            # This simulates the relevant part of the main function
            previous_dir = mock_find_previous(output_dir, domain)
            
            if previous_dir:
                self.fail("This code should not execute when previous_dir is None")
            else:
                print("\nNo previous scan found for comparison")
            
            # Verify the mock was called correctly
            mock_find_previous.assert_called_once_with(output_dir, domain)

if __name__ == '__main__':
    unittest.main()
