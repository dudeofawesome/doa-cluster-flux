"""Start Wyoming Piper with an ONNX thread pool sized for its CPU limit."""

import os
import runpy
from pathlib import Path

import onnxruntime

# Piper 2.5.2 creates default SessionOptions and exposes no thread-count flag.
# OMP_NUM_THREADS does not control this ONNX Runtime build's native thread pool.
# Keep this workaround until Piper exposes session/thread configuration.
inference_session = onnxruntime.InferenceSession


def available_cpu_threads():
    """Respect both process affinity and this cluster's cgroup v2 CPU quota."""
    threads = len(os.sched_getaffinity(0))
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
    except FileNotFoundError:
        # No visible cgroup v2 quota; affinity is the remaining bound.
        return max(1, threads)

    if quota != "max":
        # Round down fractional CPUs to avoid oversubscribing the quota.
        threads = min(threads, int(quota) // int(period))

    return max(1, threads)


def limited_inference_session(path_or_bytes, sess_options=None, **kwargs):
    options = sess_options if sess_options is not None else onnxruntime.SessionOptions()
    options.intra_op_num_threads = available_cpu_threads()
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return inference_session(path_or_bytes, sess_options=options, **kwargs)


onnxruntime.InferenceSession = limited_inference_session
runpy.run_module("wyoming_piper", run_name="__main__")
