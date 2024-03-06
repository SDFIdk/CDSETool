"""
Query the Copernicus Data Space Ecosystem OpenSearch API

https://documentation.dataspace.copernicus.eu/APIs/OpenSearch.html
"""
from xml.etree import ElementTree
from datetime import datetime, date
import re
import json
import requests
from collections import OrderedDict

class _FeatureIterator:
    def __init__(self, feature_query):
        self.index = 0
        self.feature_query = feature_query

    def __len__(self):
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

    total_results = None

    def __init__(self, collection, search_terms,fetch_odata= False):
        self.features = []
        self.fetch_odata = fetch_odata
        self.next_url = _query_url(collection, {**search_terms, "exactCount": "1"})

    def __iter__(self):
        return _FeatureIterator(self)

    def __len__(self):
        if self.total_results is None:
            self.__fetch_features()

        return self.total_results

    def __getitem__(self, index):
        while index >= len(self.features) and self.next_url is not None:
            self.__fetch_features()

        return self.features[index]

    def __fetch_features(self):
        if self.next_url is not None:
            res = requests.get(self.next_url, timeout=120).json()
            self.features += res.get("features") or []
            total_results = res.get("properties", {}).get("totalResults")
            if total_results is not None:
                self.total_results = total_results
            if self.fetch_odata:
                # if we need the odata in the query set fetch odata to True while calling the query method
                odata =self.__fetch_odata_from_product_list(self.features)
                if odata != {}:
                    self.__add_odata_to_features(odata)
            self.__set_next_url(res)

    def __fetch_odata_from_product_list(self,product_list):
        """
        Given a product list, return the odata response
        """
        body = {}
        list_products = []
        for product in product_list:
            if 'properties' in product:
                if 'title' in product['properties']:
                    list_products.append({"Name": product['properties']['title']})
        body['FilterProducts'] = list_products
        odata_url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products/OData.CSC.FilterList"
        res = self.__get_odata(odata_url,body)
        return res
    
    def __get_odata(self,url,data_json):
        """
        From the odata url and request body, get the odata response
        """
        res = requests.post(url,json=data_json, timeout=120).json()
        return res
    
    def __add_odata_to_features(self,odata):
        """
        Given the odatadict, add the to correct (by matching the Ids) checksum the features
        """
        map_id_checksum = {}
        if "value" in odata:
            odata_list_value = odata["value"]
            for ordered_dict in odata_list_value:
                map_id_checksum[ordered_dict["Id"]] = {"Checksum": ordered_dict["Checksum"], "ContentLength": ordered_dict["ContentLength"],"odata": ordered_dict}
        for feature in self.features:
            if feature.get("id") in map_id_checksum.keys():
                ordered_dict = map_id_checksum[feature.get("id")]
                feature['odata'] = ordered_dict["odata"]
                feature['Checksum'] = ordered_dict["Checksum"]
                if feature.get('properties').get('services').get('download').get('size') == ordered_dict['ContentLength']:
                    feature['ContentLength'] = ordered_dict['ContentLength']
                else:
                    print(f"Warning: content length of {feature.get('id')} does not match the ContentLength in odata")
            else:
                print(f"Warning: {feature.get('id')} not in odata")

    def __set_next_url(self, res):
        links = res.get("properties", {}).get("links") or []
        self.next_url = next(
            (link for link in links if link.get("rel") == "next"), {}
        ).get("href")

        if self.next_url:
            self.next_url = self.next_url.replace("exactCount=1", "exactCount=0")

def query_features(collection, search_terms, fetch_odata = True):
    """
    Returns an iterator over the features matching the search terms
    """
    return FeatureQuery(collection, {"maxRecords": 2000, **search_terms}, fetch_odata)


def shape_to_wkt(shape):
    """
    Convert a shapefile to a WKT string
    """
    try:
        import geopandas as gpd  # pylint: disable=import-outside-toplevel
    except ImportError:
        print(
            "geopandas is not installed. Please install it with `pip install geopandas`"
        )
    coordinates = list(gpd.read_file(shape).geometry[0].exterior.coords)
    return (
        "POLYGON(("
        + ", ".join(" ".join(map(str, coord)) for coord in coordinates)
        + "))"
    )


def geojson_to_wkt(geojson):
    """
    Convert a geojson geometry to a WKT string
    """
    if isinstance(geojson, str):
        geojson = json.loads(geojson)

    if geojson.get("type") == "Feature":
        geojson = geojson["geometry"]

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


def describe_collection(collection):
    """
    Get a list of valid options for a given collection in key value pairs
    """
    content = _get_describe_doc(collection)
    tree = ElementTree.fromstring(content)
    parameter_node_parent = tree.find(
        "{http://a9.com/-/spec/opensearch/1.1/}Url[@type='application/json']"
    )

    parameters = {}
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


def _query_url(collection, search_terms):
    description = describe_collection(collection)

    query_list = []
    for key, value in search_terms.items():
        val = _serialize_search_term(value)
        _validate_search_term(key, val, description)
        query_list.append(f"{key}={val}")

    return (
        "https://catalogue.dataspace.copernicus.eu"
        + f"/resto/api/collections/{collection}/search.json?{'&'.join(query_list)}"
    )


def _serialize_search_term(search_term):
    if isinstance(search_term, list):
        return ",".join(search_term)

    if isinstance(search_term, datetime):
        return search_term.strftime("%Y-%m-%dT%H:%M:%SZ")

    if isinstance(search_term, date):
        return search_term.strftime("%Y-%m-%d")

    return str(search_term)


def _validate_search_term(key, search_term, description):
    _assert_valid_key(key, description)
    _assert_match_pattern(search_term, description.get(key).get("pattern"))
    _assert_min_inclusive(search_term, description.get(key).get("minInclusive"))
    _assert_max_inclusive(search_term, description.get(key).get("maxInclusive"))


def _assert_valid_key(key, description):
    assert key in description.keys(), (
        f'search_term with name "{key}" '
        + "was not found for collection."
        + f" Available terms are: {', '.join(description.keys())}"
    )


def _assert_match_pattern(search_term, pattern):
    if not pattern:
        return

    assert re.match(
        pattern, search_term
    ), f"search_term {search_term} does not match pattern {pattern}"


def _assert_min_inclusive(search_term, min_inclusive):
    if not min_inclusive:
        return

    assert int(search_term) >= int(
        min_inclusive
    ), f"search_term {search_term} is less than min_inclusive {min_inclusive}"


def _assert_max_inclusive(search_term, max_inclusive):
    if not max_inclusive:
        return

    assert int(search_term) <= int(
        max_inclusive
    ), f"search_term {search_term} is greater than max_inclusive {max_inclusive}"


_describe_docs = {}


def _get_describe_doc(collection):
    if _describe_docs.get(collection):
        return _describe_docs.get(collection)

    res = requests.get(
        "https://catalogue.dataspace.copernicus.eu"
        + f"/resto/api/collections/{collection}/describe.xml",
        timeout=120,
    )
    assert res.status_code == 200, (
        f"Unable to find collection with name {collection}. Please see "
        + "https://documentation.dataspace.copernicus.eu"
        + "/APIs/OpenSearch.html#collections "
        + "for a list of available collections"
    )

    _describe_docs[collection] = res.content
    return _describe_docs.get(collection)

def get_odata_from_product_title(product_title):
    """
    Takes the name of a procuct title and returns it's odata.
    """
    body = {}
    body['FilterProducts'] = [{'Name': product_title}]
    url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products/OData.CSC.FilterList"
    res = requests.post(url,json=body, timeout=120).json()
    return res