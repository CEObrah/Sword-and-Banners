from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GITHUB_DEV = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/github-development.md"


def test_finished_ooc_dev_work_merges_without_second_confirmation():
    text = GITHUB_DEV.read_text(encoding="utf-8")

    assert "includes authority to merge the finished PR automatically" in text
    assert "once required checks are green and the branch is current" in text
    assert "review only" in text
    assert "PR only" in text
    assert "do not merge" in text
    assert "Do not stop to ask for a separate merge confirmation" in text
