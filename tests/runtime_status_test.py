"""Runtime worker status regressions."""
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core


def test_background_worker_persists_stage_and_completion():
    tmp = Path(tempfile.mkdtemp(prefix="runtime-status-"))
    old_dir = core.OUTPUT_DIR
    original_pipeline = core.run_job_pipeline
    try:
        core.OUTPUT_DIR = tmp
        job_id = "runtime000000001"
        state = core.new_job_state("runtime.docx")
        state.update(p1_done=True, p2_done=True, enable_annotate=False,
                     report_enabled=False)
        core.save_job_state(job_id, state)

        def fake_pipeline(job_id, filename, file_bytes, **kwargs):
            kwargs["on_status"]("【学术写作 10/11】定点修订受影响章节并重新验证...")
            kwargs["on_caption"]("已向模型发送章节重写请求")
            return core.load_job_state(job_id)

        core.run_job_pipeline = fake_pipeline
        assert core.start_job_worker(job_id, "runtime.docx", None, {})

        deadline = time.time() + 2
        while time.time() < deadline:
            runtime = core.load_runtime_state(job_id)
            if runtime["status"] == "completed":
                break
            time.sleep(0.01)

        runtime = core.load_runtime_state(job_id)
        assert runtime["status"] == "completed"
        assert runtime["stage"] == "academic_writing"
        assert runtime["stage_index"] == 10
        assert runtime["stage_total"] == 11
        assert runtime["overall_progress"] == 1.0
        assert any("模型发送" in item["message"] for item in runtime["events"])
    finally:
        core.run_job_pipeline = original_pipeline
        core.OUTPUT_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_background_worker_persists_stage_and_completion()
