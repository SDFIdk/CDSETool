"""
Download features from a Copernicus Data Space Ecosystem OpenSearch API result

Provides a function to download a single feature, and a function to download
all features in a result set.
"""
import os
import random
import tempfile
import time
import shutil
from cdsetool._processing import _concurrent_process
from cdsetool.credentials import Credentials
from cdsetool.monitor import NoopMonitor


def download_feature(feature, path, options=None):
    """
    Download a single feature

    Returns the feature ID
    """
    options = options or {}
    url = _get_feature_url(feature)
    filename = feature.get("properties").get("title")

    if not url or not filename:
        return feature.get("id")

    skip = options.get("skip",False)

    if skip and os.path.exists(os.path.join(path, filename.replace(".SAFE", ".zip"))):
        return feature.get("id")

    with _get_monitor(options).status() as status:
        status.set_filename(filename)

        session = _get_credentials(options).get_session()
        url = _follow_redirect(url, session)
        response = _retry_backoff(url, session)

        content_length = int(response.headers["Content-Length"])

        status.set_filesize(content_length)

        fd, tmp = tempfile.mkstemp()  # pylint: disable=invalid-name
        with open(tmp, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024 * 5):
                if not chunk:
                    continue

                file.write(chunk)
                status.add_progress(len(chunk))

        os.close(fd)
        shutil.move(tmp, os.path.join(path, filename.replace(".SAFE", ".zip")))

    return feature.get("id")


def download_features(features, path, options=None):
    """
    Generator function that downloads all features in a result set

    Feature IDs are yielded as they are downloaded
    """
    options = options or {}

    options["credentials"] = _get_credentials(options)

    options["monitor"] = _get_monitor(options)
    options["monitor"].start()

    def _download_feature(feature):
        return download_feature(feature, path, options)

    for feature in _concurrent_process(
        _download_feature, features, options.get("concurrency", 1)
    ):
        yield feature

    options["monitor"].stop()


def _get_feature_url(feature):
    return feature.get("properties").get("services").get("download").get("url")


def _follow_redirect(url, session):
    response = session.head(url, allow_redirects=False)
    while response.status_code in range(300, 400):
        url = response.headers["Location"]
        response = session.head(url, allow_redirects=False)

    return url


def _retry_backoff(url, session):
    response = session.get(url, stream=True)
    while response.status_code != 200:
        time.sleep(60 * (1 + (random.random() / 4)))
        response = session.get(url, stream=True)

    return response


def _get_monitor(options):
    return options.get("monitor") or NoopMonitor()


def _get_credentials(options):
    return options.get("credentials") or Credentials()
