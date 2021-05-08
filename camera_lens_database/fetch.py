"""Command to fetch internet resources."""
import io
import multiprocessing
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd
import typer
from tqdm.contrib.concurrent import process_map
from tqdm.std import tqdm

from . import lenses, nikon

_orig_id_map: Dict[str, str] = {}
_help_main_max_workers = (
    "Number of worker processes to launch concurrently. "
    "Specifying 0 launches the as many as CPU cores."
)


def init() -> None:
    multiprocessing.freeze_support()


def _read_nikon_lens(params: Tuple[str, str]) -> Optional[Dict[str, Union[float, str]]]:
    name, uri = params

    lens = nikon.read_lens(name, uri)
    if lens is None:
        return  # Converters

    orig_id = _orig_id_map.get(lens.name.lower())
    if orig_id is not None:
        attrs = {k: v for k, v in lens.dict().items()}
        attrs[lenses.KEY_ID] = orig_id
        lens = lenses.Lens(**attrs)
    return lens.dict()


def main(
    lenses_csv: Path = typer.Option(Path("lenses.csv")),
    max_workers: int = typer.Option(
        0, "-j", "--max-workers", help=_help_main_max_workers
    ),
    overwrite: bool = typer.Option(False, "--overwrite", "-o"),
) -> int:
    """Fetch the newest equipment data from the Web."""
    global _orig_id_map
    STR_COLUMNS = (lenses.KEY_BRAND, lenses.KEY_MOUNT, lenses.KEY_NAME)

    try:
        # Before fetching newest data, load already assigned equipment IDs
        orig_lens_data = pd.read_csv(lenses_csv)
        df = orig_lens_data.loc[:, ["ID", "Name"]]
        df = df.set_index("Name")["ID"]
        _orig_id_map = {k.lower(): v.lower() for k, v in df.to_dict().items()}

        # Gather where to find spec data
        lens_info = list(nikon.enumerate_lenses(nikon.EquipmentType.F_LENS_OLD))
        lens_info += list(nikon.enumerate_lenses(nikon.EquipmentType.F_LENS))
        lens_info += list(nikon.enumerate_lenses(nikon.EquipmentType.Z_LENS))

        # Resolve parallel processing parameters
        common_ppp: Dict[str, Union[int, str]] = {"unit": "models"}
        if max_workers <= 0:
            common_ppp["max_workers"] = multiprocessing.cpu_count()
        elif max_workers != 1:
            common_ppp["max_workers"] = max_workers

        # Fetch and analyze equipment specs
        ppp = dict(common_ppp, desc="Nikon Lens")  # see PEP 584
        specs: List[Dict[str, Union[float, str]]]
        if max_workers == 1:
            with tqdm(lens_info, **ppp) as pbar:
                spec_or_nones = [_read_nikon_lens(params) for params in pbar]
        else:
            pbar = process_map(_read_nikon_lens, lens_info, **ppp)
            spec_or_nones = [spec for spec in pbar]
        specs = [spec for spec in spec_or_nones if spec is not None]

        # Sort the result
        df = pd.DataFrame(specs)
        df = df.sort_values(
            by=[
                lenses.KEY_BRAND,
                lenses.KEY_MOUNT,
                lenses.KEY_MIN_FOCAL_LENGTH,
                lenses.KEY_MAX_FOCAL_LENGTH,
                lenses.KEY_NAME,
            ],
            kind="mergesort",
            key=lambda c: c.str.lower() if str(c) in STR_COLUMNS else c,
        )

        # Now output it
        if overwrite:
            df.to_csv(lenses_csv, index=None, float_format="%g")
        else:
            print(df.to_csv(index=None, float_format="%g"))

        return 0
    except Exception:
        with io.StringIO() as buf:
            traceback.print_exc(file=buf)
            typer.secho(str(buf.getvalue()), fg=typer.colors.RED)
        return 1
