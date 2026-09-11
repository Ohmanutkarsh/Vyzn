import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vyzn.evaluation.benchmark import BenchmarkSuite


def test_benchmark_execution():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        suite = BenchmarkSuite(output_dir=tmpdir)
        report = suite.run_full_benchmark()

        assert report["evaluation_corpus_size"] == 100
        assert "vyzn_summary" in report
        assert "naive_cctv_summary" in report
        assert "latency_breakdown" in report
        assert "effective_amortized_ms" in report["latency_breakdown"]
        assert report["false_alarm_reduction_pct"] >= 80.0
        assert report["vyzn_summary"]["metrics"]["precision"] >= 0.50

        # Check files were written
        assert os.path.exists(os.path.join(tmpdir, "benchmark_metrics.json"))
        assert os.path.exists(os.path.join(tmpdir, "benchmark_report.md"))



if __name__ == "__main__":
    test_benchmark_execution()
    print("Benchmark Suite test passed!")
