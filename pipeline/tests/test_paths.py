from pathlib import Path

import pytest

from looma_pipeline.paths import is_external, looma_file_path, to_local


@pytest.mark.parametrize("ft, expected", [
    ("video", "../content/videos/a.mp4"),       # PHP map
    ("image", "../content/pictures/a.mp4"),
    ("pdf", "../content/pdfs/a.mp4"),
    ("slideshow", "../content/slideshows/a.mp4"),
    ("worksheet", "../content/worksheets/a.mp4"),  # JavaScript-only types
    ("EP", "../content/epaath/activities/a.mp4"),
    ("unknown-type", "a.mp4"),
])
def test_default_folder_per_type_when_fp_is_missing(ft, expected):
    assert looma_file_path(ft, None, "a.mp4") == expected


def test_fp_wins_over_the_default():
    assert looma_file_path("video", "../content/Khan/science/", "x.mp4") == "../content/Khan/science/x.mp4"


def test_no_file_name_means_no_path():
    assert looma_file_path("pdf", "../content/pdfs/", "  ") is None


def test_maps_into_the_content_folder(tmp_path):
    assert to_local("../content/pdfs/a.pdf", tmp_path) == tmp_path / "pdfs" / "a.pdf"


@pytest.mark.parametrize("path", ["../content/../../etc/passwd", "../maps2018/x.html", "/etc/passwd"])
def test_paths_outside_the_content_folder_are_refused(tmp_path, path):
    assert to_local(path, tmp_path) is None


def test_external_urls_are_detected():
    assert is_external("https://looma.website/x.pdf")
    assert not is_external("../content/pdfs/x.pdf")
