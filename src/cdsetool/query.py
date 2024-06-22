"""
Query the Copernicus Data Space Ecosystem OpenSearch API

https://documentation.dataspace.copernicus.eu/APIs/OpenSearch.html
"""

from typing import Any, Dict, Union
from xml.etree import ElementTree
from datetime import datetime, date
import re
import json
import geopandas as gpd
from cdsetool.credentials import Credentials


class _FeatureIterator:
    def __init__(self, feature_query) -> None:
        self.index = 0
        self.feature_query = feature_query

    def __len__(self) -> int:
        return len(self.feature_query)

    def __iter__(self):
        return self

    def __next__(self):
        try:
            item = self.feature_query[self.index]
            self.index += 1
            return item
        except IndexError as exc:
            raise StopIteration from exc


class FeatureQuery:
    """
    An iterator over the features matching the search terms

    Queries the API in batches (default: 50) features, and returns them one by one.
    Queries the next batch when the current batch is exhausted.
    """

    total_results: int = -1

    def __init__(
        self,
        collection: str,
        search_terms: Dict[str, Any],
        proxies: Union[Dict[str, str], None] = None,
    ) -> None:
        self.features = []
        self.proxies = proxies
        self.next_url = _query_url(
            collection, {**search_terms, "exactCount": "1"}, proxies=proxies
        )

    def __iter__(self):
        return _FeatureIterator(self)

    def __len__(self) -> int:
        if self.total_results < 0:
            self.__fetch_features()

        return self.total_results

    def __getitem__(self, index):
        while index >= len(self.features) and self.next_url is not None:
            self.__fetch_features()

        return self.features[index]

    def __fetch_features(self) -> None:
        if self.next_url is None:
            return
        session = Credentials.make_session(
            None, False, Credentials.RETRIES, self.proxies
        )
        with session.get(self.next_url) as response:
            response.raise_for_status()
            res = response.json()
            self.features += res.get("features") or []

            total_results = res.get("properties", {}).get("totalResults")
            if total_results is not None:
                self.total_results = total_results

            self.__set_next_url(res)

    def __set_next_url(self, res) -> None:
        links = res.get("properties", {}).get("links") or []
        self.next_url = next(
            (link for link in links if link.get("rel") == "next"), {}
        ).get("href")

        if self.next_url:
            self.next_url = self.next_url.replace("exactCount=1", "exactCount=0")


def query_features(
    collection: str,
    search_terms: Dict[str, Any],
    proxies: Union[Dict[str, str], None] = None,
) -> FeatureQuery:
    """
    Returns an iterator over the features matching the search terms
    """
    return FeatureQuery(collection, {"maxRecords": 2000, **search_terms}, proxies)


def shape_to_wkt(shape: str) -> str:
    """
    Convert a shapefile to a WKT string
    """
    coordinates = list(gpd.read_file(shape).geometry[0].exterior.coords)
    return (
        "POLYGON(("
        + ", ".join(" ".join(map(str, coord)) for coord in coordinates)
        + "))"
    )


def geojson_to_wkt(geojson_in: Union[str, Dict]) -> str:
    """
    Convert a geojson geometry to a WKT string
    """
    geojson = json.loads(geojson_in) if isinstance(geojson_in, str) else geojson_in

    if geojson.get("type") == "Feature":
        geojson = geojson["geometry"]
    elif geojson.get("type") == "FeatureCollection" and len(geojson["features"]) == 1:
        geojson = geojson["features"][0]["geometry"]

    coordinates = str(
        tuple(item for sublist in geojson["coordinates"][0] for item in sublist)
    )
    paired_coord = ",".join(
        [
            f"{a}{b}"
            for a, b in zip(coordinates.split(",")[0::2], coordinates.split(",")[1::2])
        ]
    )
    return f"POLYGON({paired_coord})"


def describe_collection(
    collection: str, proxies: Union[Dict[str, str], None] = None
) -> Dict[str, Any]:
    """
    Get a list of valid options for a given collection in key value pairs
    """
    content = _get_describe_doc(collection, proxies=proxies)
    tree = ElementTree.fromstring(content)
    parameter_node_parent = tree.find(
        "{http://a9.com/-/spec/opensearch/1.1/}Url[@type='application/json']"
    )

    parameters = {}
    if parameter_node_parent is None:
        return parameters
    for parameter_node in parameter_node_parent:
        name = parameter_node.attrib.get("name")
        pattern = parameter_node.attrib.get("pattern")
        min_inclusive = parameter_node.attrib.get("minInclusive")
        max_inclusive = parameter_node.attrib.get("maxInclusive")
        title = parameter_node.attrib.get("title")

        if name:
            parameters[name] = {
                "pattern": pattern,
                "minInclusive": min_inclusive,
                "maxInclusive": max_inclusive,
                "title": title,
            }

    return parameters


def _query_url(
    collection: str,
    search_terms: Dict[str, Any],
    proxies: Union[Dict[str, str], None] = None,
) -> str:
    description = describe_collection(collection, proxies=proxies)

    query_list = []
    for key, value in search_terms.items():
        val = _serialize_search_term(value)
        _validate_search_term(key, val, description)
        query_list.append(f"{key}={val}")

    return (
        "https://catalogue.dataspace.copernicus.eu"
        + f"/resto/api/collections/{collection}/search.json?{'&'.join(query_list)}"
    )


def _serialize_search_term(search_term: Any) -> str:
    if isinstance(search_term, list):
        return ",".join(search_term)

    if isinstance(search_term, datetime):
        return search_term.strftime("%Y-%m-%dT%H:%M:%SZ")

    if isinstance(search_term, date):
        return search_term.strftime("%Y-%m-%d")

    return str(search_term)


def _validate_search_term(key: str, search_term: str, description) -> None:
    _assert_valid_key(key, description)
    _assert_match_pattern(search_term, description.get(key).get("pattern"))
    _assert_min_inclusive(search_term, description.get(key).get("minInclusive"))
    _assert_max_inclusive(search_term, description.get(key).get("maxInclusive"))


def _assert_valid_key(key: str, description: Dict[str, Any]) -> None:
    assert key in description.keys(), (
        f'search_term with name "{key}" '
        + "was not found for collection."
        + f" Available terms are: {', '.join(description.keys())}"
    )


def _assert_match_pattern(search_term: str, pattern: Union[str, None]) -> None:
    if not pattern:
        return

    assert re.match(
        pattern, search_term
    ), f"search_term {search_term} does not match pattern {pattern}"


def _assert_min_inclusive(search_term: str, min_inclusive: Union[str, None]) -> None:
    if not min_inclusive:
        return

    assert int(search_term) >= int(
        min_inclusive
    ), f"search_term {search_term} is less than min_inclusive {min_inclusive}"


def _assert_max_inclusive(search_term: str, max_inclusive: Union[str, None]) -> None:
    if not max_inclusive:
        return

    assert int(search_term) <= int(
        max_inclusive
    ), f"search_term {search_term} is greater than max_inclusive {max_inclusive}"


_describe_docs: Dict[str, bytes] = {}


def _get_describe_doc(
    collection: str, proxies: Union[Dict[str, str], None] = None
) -> bytes:
    docs = _describe_docs.get(collection)
    if docs:
        return docs
    session = Credentials.make_session(None, False, Credentials.RETRIES, proxies)
    with session.get(
        "https://catalogue.dataspace.copernicus.eu"
        + f"/resto/api/collections/{collection}/describe.xml",
    ) as res:
        assert res.status_code == 200, (
            f"Unable to find collection with name {collection}. Please see "
            + "https://documentation.dataspace.copernicus.eu"
            + "/APIs/OpenSearch.html#collections "
            + "for a list of available collections"
        )

        _describe_docs[collection] = res.content
        return res.content
