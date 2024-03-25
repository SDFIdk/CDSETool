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
import hashlib
from enum import Enum
from blake3 import blake3
from cdsetool._processing import _concurrent_process
from cdsetool.credentials import Credentials, TokenClientConnectionError
from cdsetool.logger import NoopLogger
from cdsetool.monitor import NoopMonitor


class Validity(Enum):
    """
    Validity enum for the checksum
    """

    VALID = 1
    INVALID = 2
    IGNORE = 3
    CONTINUE = 4


def download_feature(feature, path, options=None):
    """
    Download a single feature

    Returns the feature ID
    """
    options = options or {}
    log = _get_logger(options)
    url = _get_feature_url(feature)
    title = feature.get("properties").get("title")

    if not url or not title:
        log.debug(f"Bad URL ('{url}') or title ('{title}')")
        return None

    filename = title.replace(".SAFE", ".zip")
    result_path = os.path.join(path, filename)

    if not options.get("overwrite_existing", False) and os.path.exists(result_path):
        log.debug(f"File {result_path} already exists, skipping..")
        return filename

    with _get_monitor(options).status() as status:
        (fd, tmp) = tempfile.mkstemp()  # pylint: disable=invalid-name
        status.set_filename(filename)
        attempts = 0
        while attempts < 5:
            # Always get a new session, credentials might have expired.
            try:
                session = _get_credentials(options).get_session()
            except TokenClientConnectionError as e:
                log.warning(e)
                continue
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
                if validity_check(tmp, feature) not in (
                    Validity.VALID,
                    Validity.IGNORE,
                ):
                    log.error(f"Faulty checksum for {filename}")
                    os.remove(tmp)
                    return None
                shutil.move(tmp, result_path)
                return filename
    log.error(f"Failed to download {filename}")
    os.close(fd)
    os.remove(tmp)
    return None


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

    yield from _concurrent_process(
        _download_feature, features, options.get("concurrency", 1)
    )

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


def validity_check(temp_path, product_info):
    """Given it's temp_path and metadata info checks if the data downloaded is valid"""
    size = os.path.getsize(temp_path)
    content_length = (
        product_info.get("properties").get("services").get("download").get("size")
    )
    if size > content_length:
        return Validity.INVALID
    if size != content_length:
        # here it's a partial download logic to implement is TODO
        return Validity.CONTINUE
    return _checksum_compare(temp_path, product_info)


def _checksum_compare(temp_path, product_info):
    """Compare a given MD5 checksum with one calculated from a file."""
    checksum_list = product_info.get("Checksum", [])
    algo, checksum = from_checksum_list_to_checksum(checksum_list)
    if checksum is None:
        # no checksum available
        return Validity.IGNORE
    with open(temp_path, "rb") as f:
        while True:
            block_data = f.read(8192)
            if not block_data:
                break
            algo.update(block_data)
    return Validity.VALID if algo.hexdigest() == checksum else Validity.INVALID


def from_checksum_list_to_checksum(checksum_list):
    """
    From a list of checksum (provided by ESA if provided)
    return the checksum and algo
    """
    if not checksum_list or len(checksum_list) == 0:
        # checksum odata is not provided in the metadata
        return None, None
    algo, checksum = checksum_list[0].get("Algorithm"), checksum_list[0].get("Value")
    algo = {
        "sha3-256": hashlib.sha3_256(),
        "MD5": hashlib.md5(),
        "BLAKE3": blake3,
    }.get(algo)
    return algo, checksum
