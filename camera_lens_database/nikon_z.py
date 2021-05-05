import logging
import re
from typing import Dict, Iterator, List, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup, Tag
from bs4.element import ResultSet

from . import config, lenses
from .exceptions import CameraLensDatabaseException
from .utils import fetch

_logger = logging.getLogger(__name__)
_mount_names = {
    "ニコン Z マウント": "Nikon Z",
    "ニコン Zマウント": "Nikon Z",
}


def enumerate_lenses() -> Iterator[Tuple[str, str]]:
    base_uri = "https://www.nikon-image.com/products/nikkor/zmount/index.html"
    html_text = fetch(base_uri)
    soup = BeautifulSoup(html_text, features=config["bs_features"])
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


def read_lens(name: str, uri: str) -> Optional[lenses.Lens]:
    try:
        html_text = fetch(uri)
        soup = BeautifulSoup(html_text, config["bs_features"])
        selection = soup.select("div#spec ~ table")
        if len(selection) <= 0:
            msg = f"spec table not found: {uri}"
            raise CameraLensDatabaseException(msg)

        # Collect and parse interested th-td pairs from the spec table
        spec_table: Tag = selection[0]
        pairs: Dict[str, Union[float, str]] = {
            lenses.KEY_ID: str(uuid4()),
            lenses.KEY_NAME: name,
            lenses.KEY_BRAND: "Nikon",
            lenses.KEY_COMMENT: "",
        }
        for row in spec_table.select("tr"):
            ths: ResultSet = row.select("th")
            tds: ResultSet = row.select("td")
            if len(ths) != 1 or len(tds) != 1:
                msg = f"spec table does not have 1 by 1 th-td pairs: {uri}"
                raise CameraLensDatabaseException(msg)

            for key, value in recognize_lens_term(key=ths[0].text, value=tds[0].text):
                pairs[key] = value
        if len(pairs) != len(lenses.Lens.__fields__):
            return None

        # Compose a spec object from the table content
        return lenses.Lens(**pairs)
    except Exception as ex:
        msg = f"failed to read spec of '{name}' from {uri}: {str(ex)}"
        raise CameraLensDatabaseException(msg)


def recognize_lens_term(key: str, value: str):
    if "主レンズ" in value:
        return  # Tele-converter

    if key == "型式":
        yield lenses.KEY_MOUNT, _mount_names[value]
    elif key == "焦点距離":
        match = re.match(r"([\d\.]+)mm\s*-\s*([\d\.]+)mm", value)
        if match:
            yield lenses.KEY_MIN_FOCAL_LENGTH, float(match.group(1))
            yield lenses.KEY_MAX_FOCAL_LENGTH, float(match.group(2))
            return

        match = re.match(r"([\d\.]+)mm", value)
        if match:
            yield lenses.KEY_MIN_FOCAL_LENGTH, float(match.group(1))
            yield lenses.KEY_MAX_FOCAL_LENGTH, float(match.group(1))
            return

        msg = f"pattern unmatched: {value!r}"
        raise CameraLensDatabaseException(msg)
    elif key == "最短撮影距離":
        # 0.5 m（焦点距離50 mm）、0.52 m（焦点距離70 mm）、...
        distances: List[float] = []
        for number, unit in re.findall(r"([\d\.]+)\s*(m)", value):
            ratio = {"m": 1000, "mm": 1}[unit]
            distances.append(float(number) * ratio)
        yield lenses.KEY_MIN_FOCUS_DISTANCE, min(distances)
    elif key == "最小絞り":
        match = re.match(r"f/([\d\.]+)", value)
        if not match:
            msg = f"pattern unmatched: {value!r}"
            raise CameraLensDatabaseException(msg)
        yield lenses.KEY_MIN_F_VALUE, float(match.group(1))
    elif key == "最大絞り":
        match = re.match(r"f/([\d\.]+)", value)
        if not match:
            msg = f"pattern unmatched: {value!r}"
            raise CameraLensDatabaseException(msg)
        yield lenses.KEY_MAX_F_VALUE, float(match.group(1))
