"""Tests for ReportGenerator — CSV report generation and comparison."""
import os
import csv
import pytest
from sitemap_comparison import ReportGenerator


@pytest.fixture
def report_gen(sample_config, tmp_path):
    sample_config.output_dir = str(tmp_path)
    return ReportGenerator(sample_config)


class TestWriteCsvReport:
    """CSV files are written with correct headers and data."""

    def test_basic_csv(self, report_gen, tmp_path):
        data = [
            ("https://source.com", "https://example.com/page1"),
            ("https://source.com", "https://example.com/page2"),
        ]
        report_gen.write_csv_report("test.csv", data)

        filepath = os.path.join(str(tmp_path), "test.csv")
        assert os.path.exists(filepath)

        with open(filepath, "r", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert rows[0] == ["Source", "URL"]  # default headers
        assert rows[1] == ["https://source.com", "https://example.com/page1"]
        assert rows[2] == ["https://source.com", "https://example.com/page2"]

    def test_custom_headers(self, report_gen, tmp_path):
        data = [["New", "https://example.com/page"]]
        report_gen.write_csv_report("custom.csv", data, headers=["Status", "URL"])

        filepath = os.path.join(str(tmp_path), "custom.csv")
        with open(filepath, "r", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert rows[0] == ["Status", "URL"]

    def test_empty_data(self, report_gen, tmp_path):
        report_gen.write_csv_report("empty.csv", [])
        filepath = os.path.join(str(tmp_path), "empty.csv")
        with open(filepath, "r", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert rows[0] == ["Source", "URL"]  # header only
        assert len(rows) == 1


class TestGenerateComparisonReports:
    """Full comparison report generation: sitemap vs site URL diff."""

    def test_basic_comparison(self, report_gen):
        sitemap_urls = {
            "https://www.example.com/page1",
            "https://www.example.com/page2",
            "https://www.example.com/page3",
        }
        site_urls = {
            "https://www.example.com/page1",
            "https://www.example.com/page2",
            "https://www.example.com/page4",  # extra, not in sitemap
        }
        sitemap_sources = {u: "https://www.example.com/sitemap.xml" for u in sitemap_urls}
        site_sources = {u: "https://www.example.com" for u in site_urls}

        in_site_not_sitemap, in_sitemap_not_site = report_gen.generate_comparison_reports(
            sitemap_urls, site_urls, sitemap_sources, site_sources, has_sitemap=True
        )

        assert in_site_not_sitemap == {"https://www.example.com/page4"}
        assert in_sitemap_not_site == {"https://www.example.com/page3"}

    def test_no_sitemap(self, report_gen):
        """When has_sitemap=False, write placeholder files."""
        site_urls = {"https://www.example.com/page1"}
        site_sources = {"https://www.example.com/page1": "https://www.example.com"}

        in_site_not_sitemap, in_sitemap_not_site = report_gen.generate_comparison_reports(
            set(), site_urls, {}, site_sources, has_sitemap=False
        )

        assert in_sitemap_not_site == set()
        assert in_site_not_sitemap == site_urls

    def test_identical_sets(self, report_gen):
        """When sitemap and site match perfectly."""
        urls = {"https://www.example.com/a", "https://www.example.com/b"}
        sources = {u: "https://www.example.com" for u in urls}

        in_site_not_sitemap, in_sitemap_not_site = report_gen.generate_comparison_reports(
            urls, urls, sources, sources, has_sitemap=True
        )

        assert in_site_not_sitemap == set()
        assert in_sitemap_not_site == set()
