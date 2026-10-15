"""Start Wyoming Piper with an ONNX thread pool sized for its CPU limit."""

import os
import runpy

import onnxruntime

# Piper 2.5.2 creates default SessionOptions and exposes no thread-count flag.
# OMP_NUM_THREADS does not control this ONNX Runtime build's native thread pool.
# Keep this workaround until Piper exposes session/thread configuration.
inference_session = onnxruntime.InferenceSession


def limited_inference_session(path_or_bytes, sess_options=None, **kwargs):
    options = sess_options if sess_options is not None else onnxruntime.SessionOptions()
    options.intra_op_num_threads = int(os.environ["PIPER_INFERENCE_THREADS"])
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return inference_session(path_or_bytes, sess_options=options, **kwargs)


onnxruntime.InferenceSession = limited_inference_session
runpy.run_module("wyoming_piper", run_name="__main__")
