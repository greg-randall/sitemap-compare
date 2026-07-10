"""Tests for ThreadMonitor — thread timeout detection with callback."""
import time
import pytest
from sitemap_comparison import ThreadMonitor


class TestThreadMonitor:
    """ThreadMonitor tracks thread start/end times and fires on_timeout."""

    def test_start_stop(self):
        """Start and stop the monitoring thread."""
        tm = ThreadMonitor(max_thread_time=5)
        tm.start_monitoring()
        assert tm.monitor_running is True
        assert tm.monitor_thread is not None
        assert tm.monitor_thread.is_alive()
        tm.stop_monitoring()
        assert tm.monitor_running is False

    def test_register_start_end(self):
        """Thread start/end times are tracked."""
        tm = ThreadMonitor(max_thread_time=5)
        tm.register_thread_start("thread-1")
        assert "thread-1" in tm.thread_start_times
        tm.register_thread_end("thread-1")
        assert "thread-1" not in tm.thread_start_times

    def test_register_end_nonexistent(self):
        """Ending a non-registered thread should not raise."""
        tm = ThreadMonitor(max_thread_time=5)
        tm.register_thread_end("nonexistent")  # should not raise

    def test_timeout_callback_fires(self):
        """When a thread exceeds max_thread_time, the callback is called."""
        callbacks = []
        tm = ThreadMonitor(max_thread_time=0.1, on_timeout=lambda: callbacks.append("fired"))
        tm.start_monitoring()
        tm.register_thread_start("slow-thread")
        # Wait for monitor to detect the timeout (checks every 1s, so we need >1s wait
        # or we use a really short max_thread_time and sleep for the detection interval)
        time.sleep(1.2)
        tm.stop_monitoring()
        assert len(callbacks) >= 1
        assert "fired" in callbacks

    def test_no_callback_without_on_timeout(self):
        """If on_timeout is None, no crash when thread exceeds limit."""
        tm = ThreadMonitor(max_thread_time=0.1)
        tm.start_monitoring()
        tm.register_thread_start("slow-thread")
        time.sleep(1.2)
        tm.stop_monitoring()  # should not raise

    def test_duplicate_warning_prevented(self):
        """Once a thread is flagged, it's removed from tracking so callback fires once."""
        callbacks = []
        tm = ThreadMonitor(max_thread_time=0.1, on_timeout=lambda: callbacks.append("fired"))
        tm.start_monitoring()
        tm.register_thread_start("slow-thread")
        # First detection fires callback and removes thread from tracking
        time.sleep(1.5)
        # Second detection should NOT fire again (thread already removed)
        tm.stop_monitoring()
        # Should fire exactly once (thread removed after first warning)
        assert len(callbacks) == 1

    def test_fast_thread_not_flagged(self):
        """Threads that complete within the time limit do not trigger callback."""
        callbacks = []
        tm = ThreadMonitor(max_thread_time=5, on_timeout=lambda: callbacks.append("fired"))
        tm.start_monitoring()
        tm.register_thread_start("fast-thread")
        time.sleep(0.2)
        tm.register_thread_end("fast-thread")  # completes in time
        time.sleep(1.2)  # let monitor run
        tm.stop_monitoring()
        assert len(callbacks) == 0

    def test_multiple_threads(self):
        """Each stuck thread triggers the callback independently."""
        callbacks = []
        tm = ThreadMonitor(max_thread_time=0.1, on_timeout=lambda: callbacks.append("fired"))
        tm.start_monitoring()
        tm.register_thread_start("slow-1")
        tm.register_thread_start("slow-2")
        tm.register_thread_start("slow-3")
        time.sleep(1.2)
        tm.stop_monitoring()
        assert len(callbacks) == 3
