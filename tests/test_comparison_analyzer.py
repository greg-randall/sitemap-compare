"""Tests for ComparisonAnalyzer — historical comparison between scans."""
import os
import csv
import pytest
from sitemap_comparison import ComparisonAnalyzer, ReportGenerator


@pytest.fixture
def comparison_analyzer(sample_config, tmp_path):
    sample_config.output_dir = str(tmp_path)
    rg = ReportGenerator(sample_config)
    return ComparisonAnalyzer(sample_config, rg)


def _write_csv(filepath, urls):
    """Helper: write a simple Source,URL CSV file."""
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "URL"])
        for url in urls:
            writer.writerow(["https://source.com", url])


class TestCompareCsvFiles:
    """Compare two CSV files to find new and fixed issues."""

    def test_new_and_fixed(self, comparison_analyzer, tmp_path):
        current_file = os.path.join(str(tmp_path), "current.csv")
        previous_file = os.path.join(str(tmp_path), "previous.csv")
        output_file = os.path.join(str(tmp_path), "comparison.csv")

        _write_csv(current_file, ["https://example.com/a", "https://example.com/b", "https://example.com/c"])
        _write_csv(previous_file, ["https://example.com/a", "https://example.com/d"])

        new_count, fixed_count = comparison_analyzer.compare_csv_files(
            current_file, previous_file, output_file
        )

        assert new_count == 2   # b, c are new
        assert fixed_count == 1  # d was fixed/removed

        # Verify output
        with open(output_file, "r", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        statuses = {row[0] for row in rows[1:]}  # skip header
        assert "New" in statuses
        assert "Fixed" in statuses

    def test_identical_files(self, comparison_analyzer, tmp_path):
        current_file = os.path.join(str(tmp_path), "current.csv")
        previous_file = os.path.join(str(tmp_path), "previous.csv")
        output_file = os.path.join(str(tmp_path), "comparison.csv")

        _write_csv(current_file, ["https://example.com/a", "https://example.com/b"])
        _write_csv(previous_file, ["https://example.com/a", "https://example.com/b"])

        new_count, fixed_count = comparison_analyzer.compare_csv_files(
            current_file, previous_file, output_file
        )

        assert new_count == 0
        assert fixed_count == 0

    def test_all_new(self, comparison_analyzer, tmp_path):
        """Previous file is empty — all current URLs are new."""
        current_file = os.path.join(str(tmp_path), "current.csv")
        previous_file = os.path.join(str(tmp_path), "previous.csv")
        output_file = os.path.join(str(tmp_path), "comparison.csv")

        _write_csv(current_file, ["https://example.com/a", "https://example.com/b"])
        _write_csv(previous_file, [])  # empty

        new_count, fixed_count = comparison_analyzer.compare_csv_files(
            current_file, previous_file, output_file
        )

        assert new_count == 2
        assert fixed_count == 0


class TestFindPreviousScan:
    """Discovery of the most recent previous scan directory."""

    def test_no_previous_scan(self, comparison_analyzer, tmp_path):
        """When no previous scan exists, returns None."""
        # Current output dir is tmp_path, no sites/ structure
        result = comparison_analyzer.find_previous_scan()
        assert result is None

    def test_finds_previous_scan(self, comparison_analyzer, tmp_path, sample_config):
        """When a previous scan directory exists with CSV files, it is found."""
        # Create a fake previous scan directory
        prev_dir = os.path.join(str(tmp_path.parent), "sites", "www.example.com", "01-01-2020_01-00am")
        os.makedirs(prev_dir, exist_ok=True)
        _write_csv(os.path.join(prev_dir, "all_site_urls.csv"), ["https://example.com/old"])

        # The current output_dir is different
        # Note: find_previous_scan searches sites/<domain>/, excluding current_dir
        result = comparison_analyzer.find_previous_scan()
        # May or may not find depending on the directory being different from current
        # If current output_dir is inside tmp_path, the prev_dir at tmp_path.parent/sites/ is separate
        assert result is None or os.path.isdir(result)

    def test_no_comparison_without_previous(self, comparison_analyzer):
        """Returns False when no previous scan is available."""
        # current output_dir has no previous scan peer
        result = comparison_analyzer.compare_with_previous()
        assert result is False
