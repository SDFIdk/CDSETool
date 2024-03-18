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
from typing import Optional, Dict
from dataclasses import dataclass

from cdsetool._processing import _concurrent_process
from cdsetool.credentials import Credentials
from cdsetool.logger import NoopLogger
from cdsetool.monitor import NoopMonitor


@dataclass
class DownloadResult:
    """
    Describes the result of a download operation, whether it was successful or not.
    Contains relevant information about the feature and the download operation.
    """

    success: bool
    feature: Dict[str, any]
    filename: Optional[str]
    message: Optional[str]

    @staticmethod
    def ok(feature, filename):
        """
        Create a successful DownloadResult
        """
        return DownloadResult(True, feature, filename, None)

    @staticmethod
    def fail(feature, message):
        """
        Create a failed DownloadResult
        """
        return DownloadResult(False, feature, None, message)

    def __str__(self):
        if self.success:
            return f"Downloaded {self.feature.get('id')} to {self.filename}"

        return f"Failed to download {self.feature.get('id')}: {self.message}"


def download_feature(feature, path, options=None):
    """
    Download a single feature

    Returns a DownloadResult object
    """
    options = options or {}
    log = _get_logger(options)
    url = _get_feature_url(feature)
    title = feature.get("properties").get("title")

    if not url:
        log.debug(f"Bad URL ('{url}')")
        return DownloadResult.fail(feature, "Feature has no download URL")

    if not title:
        log.debug(f"Bad title ('{title}')")
        return DownloadResult.fail(feature, "Feature has no title")

    filename = title.replace(".SAFE", ".zip")
    result_path = os.path.join(path, filename)

    if not options.get("overwrite_existing", False) and os.path.exists(result_path):
        log.debug(f"File {result_path} already exists, skipping..")
        return DownloadResult.ok(feature, filename)

    with _get_monitor(options).status() as status:
        (fd, tmp) = tempfile.mkstemp()  # pylint: disable=invalid-name
        status.set_filename(filename)
        attempts = 0
        while attempts < 5:
            # Always get a new session, credentials might have expired.
            session = _get_credentials(options).get_session()
            url = _follow_redirect(url, session)
            with session.get(url, stream=True) as response:
                if response.status_code != 200:
                    log.warning(f"Status code {response.status_code}, retrying..")
                    attempts += 1
                    time.sleep(60 * (1 + (random.random() / 4)))
                    continue

                status.set_filesize(int(response.headers["Content-Length"]))

                with open(fd, "wb") as file:
                    for chunk in response.iter_content(chunk_size=1024 * 1024 * 5):
                        file.write(chunk)
                        status.add_progress(len(chunk))

                shutil.move(tmp, result_path)
                return DownloadResult.ok(feature, filename)
    log.error(f"Failed to download {filename}")
    os.close(fd)
    os.remove(tmp)
    return DownloadResult.fail(feature, "Failed to download after 5 attempts")


def download_features(features, path, options=None):
    """
    Generator function that downloads all features in a result set

    Feature IDs are yielded as they are downloaded
    """
    options = options or {}

    options["credentials"] = _get_credentials(options)
    options["logger"] = _get_logger(options)

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


def _get_logger(options):
    return options.get("logger") or NoopLogger()


def _get_monitor(options):
    return options.get("monitor") or NoopMonitor()


def _get_credentials(options):
    return options.get("credentials") or Credentials(
        proxies=options.get("proxies", None)
    )
