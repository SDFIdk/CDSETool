from cdsetool.query import query_features, FeatureQuery
import pytest
import requests


def _mock_metadata(requests_mock):
    file = "tests/query/mock/sentinel_1/page_6.json"
    url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products/OData.CSC.FilterList"
    with open(file, "r", encoding="utf-8") as file:
        requests_mock.post(url, text=file.read())


def _mock_describe(requests_mock):
    url = "https://catalogue.dataspace.copernicus.eu/resto/api/collections/Sentinel1/describe.xml"
    with open(
        "tests/query/mock/sentinel_1/describe.xml", "r", encoding="utf-8"
    ) as file:
        requests_mock.get(url, text=file.read())


def _mock_sentinel_1(requests_mock):
    urls = [
        (
            "tests/query/mock/sentinel_1/page_1.json",
            "https://catalogue.dataspace.copernicus.eu/resto/api/collections/Sentinel1/search.json?maxRecords=10&exactCount=1",
        ),
        (
            "tests/query/mock/sentinel_1/page_2.json",
            "https://catalogue.dataspace.copernicus.eu/resto/api/collections/Sentinel1/search.json?maxRecords=10&exactCount=0&page=2",
        ),
        (
            "tests/query/mock/sentinel_1/page_3.json",
            "https://catalogue.dataspace.copernicus.eu/resto/api/collections/Sentinel1/search.json?maxRecords=10&exactCount=0&page=3",
        ),
        (
            "tests/query/mock/sentinel_1/page_4.json",
            "https://catalogue.dataspace.copernicus.eu/resto/api/collections/Sentinel1/search.json?maxRecords=10&exactCount=0&page=4",
        ),
        (
            "tests/query/mock/sentinel_1/page_5.json",
            "https://catalogue.dataspace.copernicus.eu/resto/api/collections/Sentinel1/search.json?maxRecords=10&exactCount=0&page=5",
        ),
    ]

    for file, url in urls:
        with open(file, "r", encoding="utf-8") as file:
            requests_mock.get(url, text=file.read())


def test_query_features(requests_mock):
    _mock_describe(requests_mock)
    _mock_metadata(requests_mock)

    assert type(query_features("Sentinel1", {"maxRecords": 10})) is FeatureQuery


def test_query_features_length(requests_mock):
    _mock_describe(requests_mock)
    _mock_metadata(requests_mock)
    _mock_sentinel_1(requests_mock)

    query = query_features("Sentinel1", {"maxRecords": 10})

    assert len(query) == 48

    manual_count = 0
    for feature in query:
        manual_count += 1

    assert manual_count == 48


def test_query_features_reusable(requests_mock):
    _mock_describe(requests_mock)
    _mock_metadata(requests_mock)
    _mock_sentinel_1(requests_mock)

    query = query_features("Sentinel1", {"maxRecords": 10})

    assert len(query) == len(query)
    assert len(query) == 48  # query is not exhausted after first len call

    assert list(query) == list(query)  # query is not exhausted after first iteration


def test_query_features_random_access(requests_mock):
    _mock_describe(requests_mock)
    _mock_metadata(requests_mock)
    _mock_sentinel_1(requests_mock)

    query = query_features("Sentinel1", {"maxRecords": 10})

    assert (
        query[0]["properties"]["title"]
        == "S1A_OPER_AUX_GNSSRD_POD__20171211T101148_V20140628T235949_20140629T235939"
    )
    assert len(query.features) == 10
    assert (
        query[9]["properties"]["title"]
        == "S1A_OPER_AUX_POEORB_OPOD_20210302T165817_V20140627T225944_20140629T005944.EOF"
    )
    assert len(query.features) == 10
    assert (
        query[13]["properties"]["title"]
        == "S1A_OPER_AUX_GNSSRD_POD__20171211T095233_V20140609T235949_20140610T235939"
    )
    assert len(query.features) == 20
    assert (
        query[2]["properties"]["title"]
        == "S1A_OPER_AUX_GNSSRD_POD__20171211T095728_V20140614T235949_20140615T235939"
    )
    assert len(query.features) == 20
    assert (
        query[34]["properties"]["title"]
        == "S1A_OPER_AUX_POEORB_OPOD_20210302T133908_V20140619T225944_20140621T005944.EOF"
    )
    assert len(query.features) == 40
