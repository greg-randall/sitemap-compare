"""Tests for ObscuraResponse and obscura_fetch."""
import subprocess
import pytest
from sitemap_comparison import ObscuraResponse, obscura_fetch


class TestObscuraResponse:
    """ObscuraResponse mimics requests.Response with .text and .headers."""

    def test_basic_response(self):
        resp = ObscuraResponse("<html><body>hello</body></html>")
        assert resp.text == "<html><body>hello</body></html>"
        assert resp.status_code == 200

    def test_custom_status_code(self):
        resp = ObscuraResponse("not found", status_code=404)
        assert resp.status_code == 404
        assert resp.text == "not found"

    def test_headers_always_html(self):
        """obscura --dump html always returns rendered HTML."""
        resp = ObscuraResponse("any content")
        assert resp.headers["Content-Type"] == "text/html; charset=utf-8"

    def test_raise_for_status_ok(self):
        """No exception for status < 400."""
        resp = ObscuraResponse("ok", status_code=200)
        resp.raise_for_status()  # should not raise
        resp = ObscuraResponse("redirect", status_code=302)
        resp.raise_for_status()  # should not raise

    def test_raise_for_status_error(self):
        """Exception for status >= 400."""
        resp = ObscuraResponse("error", status_code=500)
        with pytest.raises(Exception, match="HTTP status 500"):
            resp.raise_for_status()

        resp = ObscuraResponse("not found", status_code=404)
        with pytest.raises(Exception, match="HTTP status 404"):
            resp.raise_for_status()

    def test_empty_response(self):
        """Empty stdout from obscura is valid (empty page)."""
        resp = ObscuraResponse("")
        assert resp.text == ""
        assert resp.status_code == 200


class TestObscuraFetch:
    """obscura_fetch wraps subprocess.run to call the obscura CLI."""

    def test_success(self, mocker):
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(
            stdout="<html>rendered</html>",
            stderr="",
            returncode=0,
        )
        resp = obscura_fetch("https://example.com", wait=1, wait_until="load",
                             timeout=30, stealth=False, obscura_path="obscura")
        assert resp.text == "<html>rendered</html>"
        mock_run.assert_called_once()

    def test_success_with_stealth(self, mocker):
        """--stealth flag is appended when stealth=True."""
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(
            stdout="<html>stealth</html>", stderr="", returncode=0,
        )
        resp = obscura_fetch("https://example.com", wait=2, wait_until="domcontentloaded",
                             timeout=60, stealth=True, obscura_path="/path/to/obscura")
        assert resp.text == "<html>stealth</html>"
        # Verify --stealth is in the command
        cmd = mock_run.call_args[0][0]
        assert "--stealth" in cmd
        assert cmd[0] == "/path/to/obscura"
        assert "--wait" in cmd
        assert "2" in cmd

    def test_file_not_found(self, mocker):
        """Clear error when obscura binary is missing."""
        mocker.patch("subprocess.run", side_effect=FileNotFoundError())
        with pytest.raises(Exception, match="obscura binary not found"):
            obscura_fetch("https://example.com")

    def test_timeout(self, mocker):
        """Clear error on subprocess timeout."""
        mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="obscura", timeout=30))
        with pytest.raises(Exception, match="timed out after 30s"):
            obscura_fetch("https://example.com", timeout=30)

    def test_non_zero_exit(self, mocker):
        """Error includes stderr on non-zero exit."""
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(
            stdout="", stderr="TLS handshake failed", returncode=1,
        )
        with pytest.raises(Exception, match="TLS handshake failed"):
            obscura_fetch("https://example.com")

    def test_non_zero_exit_no_stderr(self, mocker):
        """Fallback message when stderr is empty."""
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(
            stdout="", stderr="", returncode=1,
        )
        with pytest.raises(Exception, match="Unknown error"):
            obscura_fetch("https://example.com")

    def test_wait_until_passed_to_cli(self, mocker):
        """--wait-until is included in the command."""
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(stdout="ok", stderr="", returncode=0)
        obscura_fetch("https://example.com", wait_until="networkidle")
        cmd = mock_run.call_args[0][0]
        assert "--wait-until" in cmd
        assert "networkidle" in cmd
