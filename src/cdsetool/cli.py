"""
Command line interface
"""

import os
import sys
import json as JSON
from typing import Dict, List, Optional
from typing_extensions import Annotated
import typer
from cdsetool.query import describe_collection, query_features
from cdsetool.monitor import StatusMonitor
from cdsetool.download import download_features

app = typer.Typer()

query_app = typer.Typer()
app.add_typer(query_app, name="query")


@query_app.command("search-terms")
def query_search_terms(collection: str) -> None:
    """
    List the available search terms for a collection
    """
    print(f"Available search terms for collection {collection}:")
    # TODO: print validators
    for key, attributes in describe_collection(collection).items():
        print(f"  - {key}")
        if attributes.get("title"):
            print(f"    - Description: {attributes.get('title')}")
        if attributes.get("pattern"):
            print(f"    - Pattern: {attributes.get('pattern')}")
        if attributes.get("minInclusive"):
            print(f"    - Min: {attributes.get('minInclusive')}")
        if attributes.get("maxInclusive"):
            print(f"    - Max: {attributes.get('maxInclusive')}")

        print()


# TODO: implement limit
@query_app.command("search")
def query_search(
    collection: str,
    search_term: Annotated[
        Optional[List[str]],
        typer.Option(
            help="Search by term=value pairs. "
            + "Pass multiple times for multiple search terms"
        ),
    ] = None,
    json: Annotated[bool, typer.Option(help="Output JSON")] = False,
) -> None:
    """
    Search for features matching the search terms
    """
    search_term = search_term or []
    features = query_features(collection, _to_dict(search_term))

    for feature in features:
        if json:
            print(JSON.dumps(feature))
        else:
            print(feature.get("properties").get("title"))


# TODO: implement limit
@app.command("download")
def download(
    collection: str,
    path: str,
    concurrency: Annotated[
        int, typer.Option(help="Number of concurrent connections")
    ] = 1,
    overwrite_existing: Annotated[
        bool, typer.Option(help="Overwrite already downloaded files")
    ] = False,
    search_term: Annotated[
        Optional[List[str]],
        typer.Option(
            help="Search by term=value pairs. "
            + "Pass multiple times for multiple search terms"
        ),
    ] = None,
) -> None:
    """
    Download all features matching the search terms
    """
    if not os.path.exists(path):
        print(f"Path {path} does not exist")
        sys.exit(1)

    search_term = search_term or []
    features = query_features(collection, _to_dict(search_term))

    list(
        download_features(
            features,
            path,
            {
                "monitor": StatusMonitor(),
                "concurrency": concurrency,
                "overwrite_existing": overwrite_existing,
            },
        )
    )


def main():
    """
    Main entry point
    """
    app()


def _to_dict(term_list: List[str]) -> Dict[str, str]:
    search_terms = {}
    for item in term_list:
        key, value = item.split("=")
        search_terms[key] = value
    return search_terms


if __name__ == "__main__":
    main()
