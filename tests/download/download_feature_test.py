import pytest
import json
import tempfile
import os

from cdsetool.download import DownloadResult, download_feature


def test_feature_missing_url(tmpdir, feature):
    del feature["properties"]["services"]["download"]["url"]

    res = download_feature(feature, tmpdir)
    assert res.success is False
    assert res.filename is None
    assert res.message == "Feature has no download URL"
    assert (
        str(res)
        == f"Failed to download {feature.get('id')}: Feature has no download URL"
    )


def test_feature_missing_title(tmpdir, feature):
    del feature["properties"]["title"]

    res = download_feature(feature, tmpdir)
    assert res.success is False
    assert res.filename is None
    assert str(res) == f"Failed to download {feature.get('id')}: Feature has no title"


def test_skip_existing_file(tmpdir, feature):
    filename = feature["properties"]["title"].replace(".SAFE", ".zip")
    tmpfile = os.path.join(tmpdir, filename)
    with open(tmpfile, "w") as f:
        f.write("somebytes")

    res = download_feature(feature, tmpdir)
    assert res.success is True
    assert res.filename == filename
    assert res.message is None
    assert str(res) == f"Downloaded {feature.get('id')} to {filename}"


@pytest.fixture()
def feature():
    with open("tests/download/mock/feature.json") as f:
        return json.load(f)
