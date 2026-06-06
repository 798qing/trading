from pathlib import Path

from analyze import _PRIMARY_DETECTORS


REPO = Path(__file__).resolve().parents[1]
SPECS = REPO / "specs"


def test_wired_detectors_have_specs(dcfg):
    """阶段2验收：接入流水线的检测器必须有公式化规格。"""
    wired = {detector().name for detector in _PRIMARY_DETECTORS}
    missing = sorted(name for name in wired if not (SPECS / f"{name}_spec.md").exists())
    assert missing == []

    weighted = set(dcfg.get("fusion.base_weights", {}))
    wired_and_weighted = wired & weighted
    missing_weighted = sorted(
        name for name in wired_and_weighted if not (SPECS / f"{name}_spec.md").exists()
    )
    assert missing_weighted == []
