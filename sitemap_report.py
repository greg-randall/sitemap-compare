#!/usr/bin/env python3
"""
Sitemap Comparison Report Generator

A companion script for sitemap_comparison.py that generates HTML reports
from the comparison results.

Usage:
    python sitemap_report.py [--open-browser]

Options:
    --open-browser    Open the report in a web browser after generation
"""

import os
import csv
import datetime
import webbrowser
import argparse
import shutil
import json

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Generate HTML reports from sitemap comparison results')
    parser.add_argument('--open-browser', action='store_true', 
                        help='Open the report in a web browser after generation')
    parser.add_argument('--output-dir', default='reports', 
                        help='Output directory for reports (default: reports)')
    parser.add_argument('--verbose', action='store_true',
                        help='Enable verbose output for debugging')
    return parser.parse_args()

def generate_site_reports(output_dir="reports", open_browser=True, verbose=False):
    """Generate HTML reports for all sites in the sites directory."""
    if verbose:
        print(f"Starting report generation in directory: {output_dir}")
        
    # Create the reports directory if it doesn't exist
    reports_dir = output_dir
    if os.path.exists(reports_dir):
        # Clean up old reports
        if verbose:
            print(f"Cleaning up existing reports directory: {reports_dir}")
        shutil.rmtree(reports_dir)
    os.makedirs(reports_dir, exist_ok=True)
    
    # Copy the CSS file to the reports directory
    with open(os.path.join(reports_dir, "style.css"), "w", encoding="utf-8") as f:
        f.write("""
        /* Basic styles */
        body {
            font-family: Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            background-color: #f5f5f5;
        }
        h1, h2, h3 {
            color: #2c3e50;
        }
        a {
            color: #3498db;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .container {
            background-color: #fff;
            border-radius: 5px;
            padding: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .site-list {
            list-style: none;
            padding: 0;
        }
        .site-list li {
            margin-bottom: 10px;
            padding: 10px;
            background-color: #f9f9f9;
            border-radius: 4px;
        }
        .scan-list {
            list-style: none;
            padding: 0;
        }
        .scan-list li {
            margin-bottom: 10px;
            padding: 10px 15px;
            background-color: #f1f8ff;
            border-left: 3px solid #3498db;
            border-radius: 3px;
        }
        .scan-list .timestamp {
            font-weight: bold;
        }
        .scan-list .stats {
            color: #7f8c8d;
            font-size: 0.9em;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background-color: #f2f2f2;
            font-weight: bold;
        }
        tr:hover {
            background-color: #f5f5f5;
        }
        .status-new {
            color: #e74c3c;
            font-weight: bold;
        }
        .status-fixed {
            color: #27ae60;
            font-weight: bold;
        }
        .summary-box {
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 15px;
        }
        .summary-missing-site {
            background-color: #ffecec;
            border-left: 4px solid #e74c3c;
        }
        .summary-missing-sitemap {
            background-color: #e8f6fc;
            border-left: 4px solid #3498db;
        }
        .url-cell {
            word-break: break-all;
        }
        .stats-container {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        .stats-box {
            flex: 1;
            margin: 0 10px;
            padding: 15px;
            border-radius: 4px;
            text-align: center;
        }
        .stats-box h3 {
            margin-top: 0;
        }
        .stats-box .number {
            font-size: 2em;
            font-weight: bold;
            margin: 10px 0;
        }
        .nav-links {
            display: flex;
            margin-bottom: 20px;
        }
        .nav-links a {
            margin-right: 15px;
        }
        .chart-container {
            background-color: white;
            padding: 20px;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            height: 300px;
        }
        .pagination {
            display: flex;
            justify-content: center;
            margin-top: 20px;
        }
        .pagination button {
            padding: 8px 16px;
            margin: 0 5px;
            border: none;
            border-radius: 4px;
            background-color: #3498db;
            color: white;
            cursor: pointer;
        }
        .pagination button:hover {
            background-color: #2980b9;
        }
        .pagination button:disabled {
            background-color: #bdc3c7;
            cursor: not-allowed;
        }
        .table-controls {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .search-box {
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            width: 300px;
        }
        """)
    
    # Check if sites directory exists
    sites_dir = "sites"
    if not os.path.exists(sites_dir):
        print(f"Error: {sites_dir} directory not found!")
        return
    
    # Get all domains (directories inside sites/)
    domains = []
    for item in os.listdir(sites_dir):
        if os.path.isdir(os.path.join(sites_dir, item)):
            domains.append(item)
    
    if verbose:
        print(f"Found {len(domains)} domains: {', '.join(domains)}")
    
    if not domains:
        print("No domains found in the sites directory.")
        return
    
    # Generate the main index page
    if verbose:
        print("Generating main index page...")
    generate_main_index(reports_dir, domains)
    
    # Process each domain
    for domain in domains:
        if verbose:
            print(f"Processing domain: {domain}")
        domain_dir = os.path.join(sites_dir, domain)
        
        # Get all scan timestamps for this domain
        timestamps = []
        for item in os.listdir(domain_dir):
            if os.path.isdir(os.path.join(domain_dir, item)):
                timestamps.append(item)
        
        # Sort timestamps chronologically
        timestamps.sort()
        
        if verbose:
            print(f"  Found {len(timestamps)} scans for {domain}")
        
        if not timestamps:
            if verbose:
                print(f"  No scans found for {domain}, skipping")
            continue
        
        # Collect trend data
        if verbose:
            print(f"  Collecting trend data for {domain}...")
        trend_data = collect_trend_data(domain_dir, timestamps, verbose)
        
        # Generate domain index page
        domain_report_dir = os.path.join(reports_dir, domain)
        os.makedirs(domain_report_dir, exist_ok=True)
        
        # Generate the domain index page
        if verbose:
            print(f"  Generating index page for {domain}...")
        generate_domain_index(domain, domain_dir, domain_report_dir, timestamps, trend_data)
        
        # Process each scan (now using reversed timestamps for newest first)
        for timestamp in reversed(timestamps):
            if verbose:
                print(f"  Generating report for scan: {timestamp}")
            scan_dir = os.path.join(domain_dir, timestamp)
            generate_scan_report(domain, timestamp, scan_dir, domain_report_dir, verbose)
    
    # Open the main index in the browser if requested
    index_path = os.path.join(reports_dir, "index.html")
    print(f"Reports generated at: {os.path.abspath(index_path)}")
    if open_browser:
        try:
            webbrowser.open_new_tab(f"file://{os.path.abspath(index_path)}")
        except:
            print("Could not open browser automatically.")

def collect_trend_data(domain_dir, timestamps, verbose=False):
    """Collect trend data for all scans of a domain."""
    trend_data = {
        "labels": [],
        "missing_site": [],
        "missing_sitemap": []
    }
    
    if verbose:
        print(f"    Collecting data from {len(timestamps)} timestamps")
    
    for timestamp in timestamps:
        # Parse timestamp for better labeling
        try:
            dt = datetime.datetime.strptime(timestamp, "%m-%d-%Y_%I-%M%p")
            formatted_date = dt.strftime("%m/%d/%Y")
        except:
            formatted_date = timestamp
        
        trend_data["labels"].append(formatted_date)
        
        scan_dir = os.path.join(domain_dir, timestamp)
        
        # Check for both CSV and TXT files
        missing_site_file = os.path.join(scan_dir, "missing_from_site.csv")
        if not os.path.exists(missing_site_file):
            missing_site_file = os.path.join(scan_dir, "missing_from_site.txt")
        
        missing_sitemap_file = os.path.join(scan_dir, "missing_from_sitemap.csv")
        if not os.path.exists(missing_sitemap_file):
            missing_sitemap_file = os.path.join(scan_dir, "missing_from_sitemap.txt")
        
        # Get counts
        missing_site_count = count_csv_rows(missing_site_file, verbose)
        missing_sitemap_count = count_csv_rows(missing_sitemap_file, verbose)
        
        if verbose:
            print(f"    Timestamp {timestamp}: {missing_site_count} missing from site, {missing_sitemap_count} missing from sitemap")
        
        trend_data["missing_site"].append(missing_site_count)
        trend_data["missing_sitemap"].append(missing_sitemap_count)
    
    return trend_data

def generate_main_index(reports_dir, domains):
    """Generate the main index page listing all domains."""
    with open(os.path.join(reports_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Sitemap Comparison Reports</title>
            <link rel="stylesheet" href="style.css">
        </head>
        <body>
            <div class="container">
                <h1>Sitemap Comparison Reports</h1>
                <p>Select a domain to view detailed reports:</p>
                <ul class="site-list">
        """)
        
        # Add domains
        for domain in sorted(domains):
            # Get the latest scan date for this domain
            domain_dir = os.path.join("sites", domain)
            timestamps = [item for item in os.listdir(domain_dir) if os.path.isdir(os.path.join(domain_dir, item))]
            timestamps.sort(reverse=True)
            
            latest_timestamp = "No scans" if not timestamps else timestamps[0]
            try:
                dt = datetime.datetime.strptime(latest_timestamp, "%m-%d-%Y_%I-%M%p")
                formatted_date = dt.strftime("%B %d, %Y")
            except:
                formatted_date = latest_timestamp
            
            f.write(f'<li><a href="{domain}/index.html">{domain}</a> <span style="color: #7f8c8d;">(Latest scan: {formatted_date})</span></li>\n')
        
        f.write("""
                </ul>
            </div>
        </body>
        </html>
        """)

def generate_domain_index(domain, domain_dir, domain_report_dir, timestamps, trend_data):
    """Generate the index page for a domain showing all scans and trend chart."""
    with open(os.path.join(domain_report_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Sitemap Comparison - {domain}</title>
            <link rel="stylesheet" href="../style.css">
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        </head>
        <body>
            <div class="container">
                <div class="nav-links">
                    <a href="../index.html">← Back to all domains</a>
                </div>
                <h1>Sitemap Comparison for {domain}</h1>
                
                <h2>Trends Over Time</h2>
                <div class="chart-container">
                    <canvas id="trendChart"></canvas>
                </div>
                <script>
                    const ctx = document.getElementById('trendChart').getContext('2d');
                    const trendChart = new Chart(ctx, {{
                        type: 'line',
                        data: {{
                            labels: {json.dumps(trend_data["labels"])},
                            datasets: [
                                {{
                                    label: 'URLs Missing from Site',
                                    data: {json.dumps(trend_data["missing_site"])},
                                    borderColor: '#e74c3c',
                                    backgroundColor: 'rgba(231, 76, 60, 0.1)',
                                    tension: 0.1,
                                    fill: true
                                }},
                                {{
                                    label: 'URLs Missing from Sitemap',
                                    data: {json.dumps(trend_data["missing_sitemap"])},
                                    borderColor: '#3498db',
                                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                                    tension: 0.1,
                                    fill: true
                                }}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {{
                                title: {{
                                    display: true,
                                    text: 'Missing URLs Over Time'
                                }}
                            }},
                            scales: {{
                                y: {{
                                    beginAtZero: true,
                                    title: {{
                                        display: true,
                                        text: 'Number of URLs'
                                    }}
                                }},
                                x: {{
                                    title: {{
                                        display: true,
                                        text: 'Scan Date'
                                    }}
                                }}
                            }}
                        }}
                    }});
                </script>
                
                <h2>Scan History</h2>
                <p>Select a scan to view detailed report:</p>
                <ul class="scan-list">
        """)
        
        # Process each scan to get summary information (reversed for newest first)
        for timestamp in reversed(timestamps):
            scan_dir = os.path.join(domain_dir, timestamp)
            
            # Parse the timestamp
            try:
                dt = datetime.datetime.strptime(timestamp, "%m-%d-%Y_%I-%M%p")
                formatted_date = dt.strftime("%B %d, %Y at %I:%M %p")
            except:
                formatted_date = timestamp
            
            # Get the counts for missing URLs
            missing_site_count = count_csv_rows(os.path.join(scan_dir, "missing_from_site.csv"))
            missing_sitemap_count = count_csv_rows(os.path.join(scan_dir, "missing_from_sitemap.csv"))
            
            # Check if comparison files exist
            has_comparison = (
                os.path.exists(os.path.join(scan_dir, "comparison_missing_from_site.csv")) and
                os.path.exists(os.path.join(scan_dir, "comparison_missing_from_sitemap.csv"))
            )
            
            comparison_text = ""
            if has_comparison:
                new_missing_site, fixed_missing_site = count_comparison_csv(
                    os.path.join(scan_dir, "comparison_missing_from_site.csv")
                )
                new_missing_sitemap, fixed_missing_sitemap = count_comparison_csv(
                    os.path.join(scan_dir, "comparison_missing_from_sitemap.csv")
                )
                
                comparison_text = f"""
                <div class="stats">
                    <strong>Changes since previous scan:</strong> 
                    <span class="status-new">{new_missing_site} new</span> / 
                    <span class="status-fixed">{fixed_missing_site} fixed</span> missing from site, 
                    <span class="status-new">{new_missing_sitemap} new</span> / 
                    <span class="status-fixed">{fixed_missing_sitemap} fixed</span> missing from sitemap
                </div>
                """
            
            f.write(f"""
                <li>
                    <a href="{timestamp}.html" class="timestamp">{formatted_date}</a>
                    <div class="stats">
                        <strong>Issues:</strong> {missing_site_count} URLs missing from site, {missing_sitemap_count} URLs missing from sitemap
                    </div>
                    {comparison_text}
                </li>
            """)
        
        f.write("""
                </ul>
            </div>
        </body>
        </html>
        """)

def generate_scan_report(domain, timestamp, scan_dir, domain_report_dir, verbose=False):
    """Generate the detailed report for a single scan."""
    if verbose:
        print(f"    Generating scan report for {domain} - {timestamp}")
    # Parse the timestamp
    try:
        dt = datetime.datetime.strptime(timestamp, "%m-%d-%Y_%I-%M%p")
        formatted_date = dt.strftime("%B %d, %Y at %I:%M %p")
    except:
        formatted_date = timestamp
    
    # Check for both CSV and TXT files
    missing_site_file = os.path.join(scan_dir, "missing_from_site.csv")
    if not os.path.exists(missing_site_file):
        missing_site_file = os.path.join(scan_dir, "missing_from_site.txt")
    
    missing_sitemap_file = os.path.join(scan_dir, "missing_from_sitemap.csv")
    if not os.path.exists(missing_sitemap_file):
        missing_sitemap_file = os.path.join(scan_dir, "missing_from_sitemap.txt")
    
    if verbose:
        print(f"      Using files: {missing_site_file} and {missing_sitemap_file}")
    
    # Read the missing from site data
    missing_site_data = read_csv_data(missing_site_file, verbose)
    missing_site_count = len(missing_site_data)
    
    # Read the missing from sitemap data
    missing_sitemap_data = read_csv_data(missing_sitemap_file, verbose)
    missing_sitemap_count = len(missing_sitemap_data)
    
    # Check if comparison files exist
    has_comparison = (
        os.path.exists(os.path.join(scan_dir, "comparison_missing_from_site.csv")) and
        os.path.exists(os.path.join(scan_dir, "comparison_missing_from_sitemap.csv"))
    )
    
    comparison_site_data = []
    comparison_sitemap_data = []
    
    if has_comparison:
        comparison_site_data = read_csv_data(os.path.join(scan_dir, "comparison_missing_from_site.csv"))
        comparison_sitemap_data = read_csv_data(os.path.join(scan_dir, "comparison_missing_from_sitemap.csv"))
    
    # Generate the HTML file
    with open(os.path.join(domain_report_dir, f"{timestamp}.html"), "w", encoding="utf-8") as f:
        f.write(f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Scan Report - {domain} - {timestamp}</title>
            <link rel="stylesheet" href="../style.css">
        </head>
        <body>
            <div class="container">
                <div class="nav-links">
                    <a href="index.html">← Back to {domain} scans</a>
                </div>
                <h1>Sitemap Comparison Scan Report</h1>
                <p><strong>Domain:</strong> {domain}</p>
                <p><strong>Scan Date:</strong> {formatted_date}</p>
                
                <div class="stats-container">
                    <div class="stats-box summary-missing-site">
                        <h3>URLs in Sitemap but Missing from Site</h3>
                        <div class="number">{missing_site_count}</div>
                    </div>
                    <div class="stats-box summary-missing-sitemap">
                        <h3>URLs in Site but Missing from Sitemap</h3>
                        <div class="number">{missing_sitemap_count}</div>
                    </div>
                </div>
        """)
        
        # Add comparison section if available
        if has_comparison:
            new_missing_site = sum(1 for row in comparison_site_data if row["Status"] == "New")
            fixed_missing_site = sum(1 for row in comparison_site_data if row["Status"] == "Fixed")
            new_missing_sitemap = sum(1 for row in comparison_sitemap_data if row["Status"] == "New")
            fixed_missing_sitemap = sum(1 for row in comparison_sitemap_data if row["Status"] == "Fixed")
            
            f.write(f"""
                <h2>Changes Since Previous Scan</h2>
                <div class="stats-container">
                    <div class="stats-box summary-missing-site">
                        <h3>Missing from Site</h3>
                        <div><span class="status-new">{new_missing_site} new issues</span></div>
                        <div><span class="status-fixed">{fixed_missing_site} fixed issues</span></div>
                    </div>
                    <div class="stats-box summary-missing-sitemap">
                        <h3>Missing from Sitemap</h3>
                        <div><span class="status-new">{new_missing_sitemap} new issues</span></div>
                        <div><span class="status-fixed">{fixed_missing_sitemap} fixed issues</span></div>
                    </div>
                </div>
            """)
        
        # URLs Missing from Site section
        f.write("""
                <h2>URLs in Sitemap but Missing from Site</h2>
                <div class="summary-box summary-missing-site">
                    These URLs were found in the sitemap but could not be accessed when spidering the website. 
                    They might be broken links, require authentication, or have been blocked by robots.txt.
                </div>
        """)
        
        if missing_site_data:
            f.write("""
                <div class="table-controls">
                    <input type="text" class="search-box" id="missingFromSiteSearch" placeholder="Search URLs...">
                </div>
                <table id="missingFromSiteTable">
                    <thead>
                        <tr>
                            <th>Source</th>
                            <th>URL</th>
                        </tr>
                    </thead>
                    <tbody>
            """)
            
            for row in missing_site_data:
                source = row.get("Source", "")
                url = row.get("URL", "")
                f.write(f"""
                        <tr>
                            <td>{source}</td>
                            <td class="url-cell"><a href="{url}" target="_blank">{url}</a></td>
                        </tr>
                """)
            
            f.write("""
                    </tbody>
                </table>
                <div class="pagination" id="missingFromSitePagination"></div>
            """)
        else:
            f.write("<p>No URLs missing from site.</p>")
        
        # URLs Missing from Sitemap section
        f.write("""
                <h2>URLs in Site but Missing from Sitemap</h2>
                <div class="summary-box summary-missing-sitemap">
                    These URLs were found while spidering the website but were not in the sitemap. 
                    Consider adding them to your sitemap for better search engine visibility.
                </div>
        """)
        
        if missing_sitemap_data:
            f.write("""
                <div class="table-controls">
                    <input type="text" class="search-box" id="missingFromSitemapSearch" placeholder="Search URLs...">
                </div>
                <table id="missingFromSitemapTable">
                    <thead>
                        <tr>
                            <th>Source</th>
                            <th>URL</th>
                        </tr>
                    </thead>
                    <tbody>
            """)
            
            for row in missing_sitemap_data:
                source = row.get("Source", "")
                url = row.get("URL", "")
                f.write(f"""
                        <tr>
                            <td>{source}</td>
                            <td class="url-cell"><a href="{url}" target="_blank">{url}</a></td>
                        </tr>
                """)
            
            f.write("""
                    </tbody>
                </table>
                <div class="pagination" id="missingFromSitemapPagination"></div>
            """)
        else:
            f.write("<p>No URLs missing from sitemap.</p>")
        
        # Add detailed comparison tables if available
        if comparison_site_data:
            f.write("""
                <h2>Detailed Changes - URLs Missing from Site</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Status</th>
                            <th>URL</th>
                        </tr>
                    </thead>
                    <tbody>
            """)
            
            for row in comparison_site_data:
                status = row.get("Status", "")
                url = row.get("URL", "")
                status_class = f"status-{status.lower()}" if status in ["New", "Fixed"] else ""
                
                f.write(f"""
                        <tr>
                            <td class="{status_class}">{status}</td>
                            <td class="url-cell"><a href="{url}" target="_blank">{url}</a></td>
                        </tr>
                """)
            
            f.write("""
                    </tbody>
                </table>
            """)
        
        if comparison_sitemap_data:
            f.write("""
                <h2>Detailed Changes - URLs Missing from Sitemap</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Status</th>
                            <th>URL</th>
                        </tr>
                    </thead>
                    <tbody>
            """)
            
            for row in comparison_sitemap_data:
                status = row.get("Status", "")
                url = row.get("URL", "")
                status_class = f"status-{status.lower()}" if status in ["New", "Fixed"] else ""
                
                f.write(f"""
                        <tr>
                            <td class="{status_class}">{status}</td>
                            <td class="url-cell"><a href="{url}" target="_blank">{url}</a></td>
                        </tr>
                """)
            
            f.write("""
                    </tbody>
                </table>
            """)
        
        # Add JavaScript for table filtering and pagination
        f.write("""
                <script>
                // Table pagination and filtering
                class TablePaginator {
                    constructor(tableId, paginationId, searchId, rowsPerPage = 25) {
                        this.table = document.getElementById(tableId);
                        if (!this.table) return;
                        
                        this.pagination = document.getElementById(paginationId);
                        this.searchInput = document.getElementById(searchId);
                        this.rowsPerPage = rowsPerPage;
                        this.currentPage = 1;
                        
                        this.rows = Array.from(this.table.querySelectorAll('tbody tr'));
                        this.filteredRows = [...this.rows];
                        
                        this.initSearch();
                        this.initPagination();
                        this.update();
                    }
                    
                    initSearch() {
                        if (!this.searchInput) return;
                        
                        this.searchInput.addEventListener('input', () => {
                            this.currentPage = 1;
                            this.filterRows();
                            this.update();
                        });
                    }
                    
                    filterRows() {
                        if (!this.searchInput) {
                            this.filteredRows = [...this.rows];
                            return;
                        }
                        
                        const searchTerm = this.searchInput.value.toLowerCase();
                        if (!searchTerm) {
                            this.filteredRows = [...this.rows];
                            return;
                        }
                        
                        this.filteredRows = this.rows.filter(row => {
                            return Array.from(row.cells).some(cell => 
                                cell.textContent.toLowerCase().includes(searchTerm)
                            );
                        });
                    }
                    
                    initPagination() {
                        if (!this.pagination) return;
                        
                        this.updatePaginationControls();
                    }
                    
                    updatePaginationControls() {
                        if (!this.pagination) return;
                        
                        const totalPages = Math.ceil(this.filteredRows.length / this.rowsPerPage);
                        this.pagination.innerHTML = '';
                        
                        if (totalPages <= 1) return;
                        
                        // Previous button
                        const prevButton = document.createElement('button');
                        prevButton.textContent = '← Previous';
                        prevButton.disabled = this.currentPage === 1;
                        prevButton.addEventListener('click', () => {
                            this.currentPage--;
                            this.update();
                        });
                        this.pagination.appendChild(prevButton);
                        
                        // Page info
                        const pageInfo = document.createElement('span');
                        pageInfo.textContent = ` Page ${this.currentPage} of ${totalPages} `;
                        pageInfo.style.margin = '0 10px';
                        this.pagination.appendChild(pageInfo);
                        
                        // Next button
                        const nextButton = document.createElement('button');
                        nextButton.textContent = 'Next →';
                        nextButton.disabled = this.currentPage === totalPages;
                        nextButton.addEventListener('click', () => {
                            this.currentPage++;
                            this.update();
                        });
                        this.pagination.appendChild(nextButton);
                    }
                    
                    update() {
                        // Hide all rows
                        this.rows.forEach(row => row.style.display = 'none');
                        
                        // Show filtered rows for current page
                        const start = (this.currentPage - 1) * this.rowsPerPage;
                        const end = start + this.rowsPerPage;
                        
                        this.filteredRows.slice(start, end).forEach(row => row.style.display = '');
                        
                        // Update pagination controls
                        this.updatePaginationControls();
                    }
                }
                
                // Initialize paginators when page is loaded
                document.addEventListener('DOMContentLoaded', function() {
                    if (document.getElementById('missingFromSiteTable')) {
                        new TablePaginator('missingFromSiteTable', 'missingFromSitePagination', 'missingFromSiteSearch');
                    }
                    
                    if (document.getElementById('missingFromSitemapTable')) {
                        new TablePaginator('missingFromSitemapTable', 'missingFromSitemapPagination', 'missingFromSitemapSearch');
                    }
                });
                </script>
            </div>
        </body>
        </html>
        """)

def count_csv_rows(file_path, verbose=False):
    """Count the number of data rows in a CSV file or text file."""
    if not os.path.exists(file_path):
        if verbose:
            print(f"      File not found: {file_path}")
        return 0
    
    try:
        with open(file_path, 'r', newline='') as f:
            # Try to read as CSV first
            try:
                reader = csv.reader(f)
                # Skip header
                next(reader, None)
                count = sum(1 for _ in reader)
                if verbose:
                    print(f"      Counted {count} rows in CSV: {file_path}")
                return count
            except Exception:
                # If CSV reading fails, try as a simple text file with URLs
                if verbose:
                    print(f"      Failed to count as CSV, trying as text file: {file_path}")
                
                # Reset file pointer to beginning
                f.seek(0)
                
                # Count non-empty, non-comment lines
                count = sum(1 for line in f if line.strip() and not line.strip().startswith('#'))
                if verbose:
                    print(f"      Counted {count} URLs in text file: {file_path}")
                return count
    except Exception as e:
        print(f"Error counting rows in {file_path}: {e}")
        return 0

def count_comparison_csv(file_path):
    """Count the number of new and fixed issues in a comparison CSV file."""
    new_count = 0
    fixed_count = 0
    
    if not os.path.exists(file_path):
        return new_count, fixed_count
    
    try:
        with open(file_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Status") == "New":
                    new_count += 1
                elif row.get("Status") == "Fixed":
                    fixed_count += 1
    except Exception as e:
        print(f"Error counting comparison in {file_path}: {e}")
    
    return new_count, fixed_count

def read_csv_data(file_path, verbose=False):
    """Read a CSV file and return the data as a list of dictionaries."""
    data = []
    
    if not os.path.exists(file_path):
        if verbose:
            print(f"      File not found: {file_path}")
        return data
    
    try:
        with open(file_path, 'r', newline='') as f:
            # Try to read as CSV first
            try:
                reader = csv.DictReader(f)
                for row in reader:
                    data.append(row)
                
                if verbose:
                    print(f"      Read {len(data)} rows from CSV: {file_path}")
                
                return data
            except Exception as csv_error:
                # If CSV reading fails, try as a simple text file with URLs
                if verbose:
                    print(f"      Failed to read as CSV, trying as text file: {file_path}")
                
                # Reset file pointer to beginning
                f.seek(0)
                
                # Read as text file with one URL per line
                lines = f.readlines()
                for line in lines:
                    url = line.strip()
                    if url and not url.startswith('#'):  # Skip empty lines and comments
                        data.append({"URL": url, "Source": "Text file"})
                
                if verbose:
                    print(f"      Read {len(data)} URLs from text file: {file_path}")
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
    
    return data

if __name__ == "__main__":
    args = parse_args()
    generate_site_reports(args.output_dir, args.open_browser, args.verbose)
