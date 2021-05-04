import logging
import re
from typing import Iterator, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from bs4.element import ResultSet

from . import (
    IDX_BRAND,
    IDX_MAX_F_VALUE,
    IDX_MAX_FOCAL_LENGTH,
    IDX_MIN_F_VALUE,
    IDX_MIN_FOCAL_LENGTH,
    IDX_MIN_FOCUS_DISTANCE,
    IDX_MOUNT,
    IDX_NAME,
    LensSpec,
    ScraperException,
    config,
)

_logger = logging.getLogger(__name__)
_mount_names = {
    "ニコン Z マウント": "Nikon Z",
    "ニコン Zマウント": "Nikon Z",
}


def enumerate_nikon_z_lens() -> Iterator[Tuple[str, str]]:
    # From: "https://www.nikon-image.com/products/nikkor/zmount/index.html"
    # To:   "https://www.nikon-image.com/products/nikkor/zmount/NAME/spec.html"
    base_uri = "https://www.nikon-image.com/products/nikkor/zmount/index.html"
    resp = requests.get(base_uri)
    soup = BeautifulSoup(resp.text, features=config["bs_features"])
    for anchor in soup.select(".mod-goodsList-ul > li > a"):
        # Get the equipment name
        name = anchor.select(".mod-goodsList-title")[0].text

        # Get raw value of href attribute
        raw_dest = anchor["href"]
        if raw_dest.startswith("javascript:"):
            continue

        # Check the destination looks fine
        pr = urlparse(raw_dest)
        if pr.hostname and pr.hostname != base_uri:
            _logger.warning(
                "skipped an item because it's not on the same server: %r",
                anchor["href"],
                base_uri,
            )
            continue

        # Construct an absolute URI
        rel_dest = pr.path
        abs_dest = urljoin(base_uri, rel_dest)
        abs_dest = urljoin(abs_dest, "spec.html")

        yield name, abs_dest


def read_nikon_z_lens(name: str, uri: str):
    # https://www.nikon-image.com/products/nikkor/zmount/NAME/spec.html
    try:
        resp = requests.get(uri)
        soup = BeautifulSoup(resp.text, config["bs_features"])
        selection = soup.select("div#spec ~ table")
        if len(selection) <= 0:
            msg = f"spec table not found: {uri}"
            raise ScraperException(msg)

        # Collect interested th-td pairs from the spec table
        spec_table: Tag = selection[0]
        pairs = [(IDX_NAME, name), (IDX_BRAND, "Nikon")]
        for row in spec_table.select("tr"):
            ths: ResultSet = row.select("th")
            tds: ResultSet = row.select("td")
            if len(ths) != 1 or len(tds) != 1:
                msg = f"spec table does not have 1 by 1 th-td pairs: {uri}"
                raise ScraperException(msg)

            for index, value in recognize_nikon_z_term(
                key=ths[0].text, value=tds[0].text
            ):
                pairs.append((index, value))
        values = dict(pairs)

        return LensSpec(
            name=values[IDX_NAME],
            brand=values[IDX_BRAND],
            mount=values[IDX_MOUNT],
            min_focal_length=values[IDX_MIN_FOCAL_LENGTH],
            max_focal_length=values[IDX_MAX_FOCAL_LENGTH],
            min_f_value=values[IDX_MIN_F_VALUE],
            max_f_value=values[IDX_MAX_F_VALUE],
            min_focus_distance=values[IDX_MIN_FOCUS_DISTANCE],
        )
    except Exception:
        _logger.exception("failed to read spec of '%s' from %s", name, uri)
        raise


def recognize_nikon_z_term(key: str, value: str):
    if key == "型式":
        yield IDX_MOUNT, _mount_names[value]
    elif key == "焦点距離":
        match = re.match(r"([\d\.]+)mm\s*-\s*([\d\.]+)mm", value)
        if not match:
            msg = f"pattern unmatched: {value!r}"
            raise ScraperException(msg)
        yield IDX_MIN_FOCAL_LENGTH, match.group(1)
        yield IDX_MAX_FOCAL_LENGTH, match.group(2)
    elif key == "最短撮影距離":
        # 0.5 m（焦点距離50 mm）、0.52 m（焦点距離70 mm）、...
        distances = []
        for number, unit in re.findall(r"([\d\.]+)\s*(m)", value):
            ratio = {"m": 1000, "mm": 1}[unit]
            distances.append(float(number) * ratio)
        yield IDX_MIN_FOCUS_DISTANCE, min(distances)
    elif key == "最小絞り":
        match = re.match(r"f/([\d\.]+)", value)
        if not match:
            msg = f"pattern unmatched: {value!r}"
            raise ScraperException(msg)
        yield IDX_MIN_F_VALUE, match.group(1)
    elif key == "最大絞り":
        match = re.match(r"f/([\d\.]+)", value)
        if not match:
            msg = f"pattern unmatched: {value!r}"
            raise ScraperException(msg)
        yield IDX_MAX_F_VALUE, match.group(1)
