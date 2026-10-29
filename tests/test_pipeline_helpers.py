from app.pipeline import _titles_are_similar


def test_detects_same_story_with_minor_title_changes():
    assert _titles_are_similar(
        "Manchester United signs a new striker after negotiations",
        "Manchester United signs new striker after negotiations",
    )


def test_does_not_merge_unrelated_titles():
    assert not _titles_are_similar(
        "Liverpool beats Chelsea in cup quarter-final",
        "Real Madrid announces a new stadium project",
    )
