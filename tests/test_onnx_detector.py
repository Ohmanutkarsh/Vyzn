"""
Unit test for AGPL-3.0 free ONNX / OpenCV DNN detector.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from vyzn.ai.detector import get_detector, MockDetector
from vyzn.ai.onnx_detector import ONNXDetector



def test_onnx_detector_initialization_and_fallback():
    # Test initialization without weights (should safely operate in fallback)
    detector = ONNXDetector(model_path="non_existent_weights.onnx")
    assert detector.backend_name == "fallback"

    # Test detection on clean background
    blank = np.full((360, 640, 3), 150, dtype=np.uint8)
    dets = detector.detect(blank)
    assert len(dets) == 0

    # Test detection on frame with dark synthetic object
    frame_with_person = blank.copy()
    frame_with_person[100:300, 200:350] = 30
    dets = detector.detect(frame_with_person)
    assert len(dets) >= 1
    assert dets[0].label == "person"
    assert dets[0].confidence > 0.5


def test_detector_factory():
    d_mock = get_detector("mock")
    assert isinstance(d_mock, MockDetector)

    d_onnx = get_detector("onnx")
    assert isinstance(d_onnx, ONNXDetector)


if __name__ == "__main__":
    test_onnx_detector_initialization_and_fallback()
    test_detector_factory()
    print("ONNX Detector tests passed!")
