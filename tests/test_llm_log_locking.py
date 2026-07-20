"""llm.log is written by both bot.py and autonomy.py (separate processes).
The old rotate-then-append had no locking: one process's rotation truncate
could race another's in-flight append. _log/_append must serialize access
via an exclusive flock so rotation and writes never interleave across
processes."""
import fcntl
import re
import threading

import llm


def test_log_write_acquires_and_releases_exclusive_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "LOG_PATH", str(tmp_path / "llm.log"))
    calls = []
    real_flock = fcntl.flock

    def spy_flock(fd, op):
        calls.append(op)
        return real_flock(fd, op)

    monkeypatch.setattr(fcntl, "flock", spy_flock)
    llm._log("caller", 12.0, True)

    assert fcntl.LOCK_EX in calls
    assert fcntl.LOCK_UN in calls
    assert calls.index(fcntl.LOCK_EX) < calls.index(fcntl.LOCK_UN)


def test_concurrent_writes_produce_only_well_formed_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "LOG_PATH", str(tmp_path / "llm.log"))
    monkeypatch.setattr(llm, "LLM_LOG_MAX_BYTES", 400)  # force frequent rotation

    def worker(n):
        for i in range(15):
            llm._log("workerfn", 1.0, True, f"thread={n} i={i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    text = (tmp_path / "llm.log").read_text()
    lines = [l for l in text.splitlines() if l]
    line_re = re.compile(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} caller=workerfn "
        r"latency_ms=\d+ status=ok thread=\d+ i=\d+$"
    )
    assert lines, "expected at least some lines to survive rotation"
    for l in lines:
        assert line_re.match(l), f"corrupted/interleaved line: {l!r}"
