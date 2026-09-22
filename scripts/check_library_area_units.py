#!/usr/bin/env python3
"""Read private Liberty/LEF/DC inputs; publish only hashes and aggregate checks.

No EDA executable or license is used. ``pdftotext`` checks the public LEF SIZE
definition and the optional supplier kit compatibility table. Archive members
are read in memory and never extracted. --lib and --lef have no path defaults.
The final check remains incomplete without a matching --dc-area export and --db.
"""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_URL = "https://www.ispd.cc/contests/18/lefdefref.pdf"
REFERENCE_SHA256 = "94c98fb198c418088e80cb7ce7bb4045840a0f447dab990f53506f68622c18ed"
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_input(path, member, tracked):
    path = Path(path).resolve()
    raw = path.read_bytes()
    tracked[path] = sha(raw)
    record = {"basename": path.name, "sha256": sha(raw)}
    if member:
        with tarfile.open(path, "r:*") as archive:
            item = archive.getmember(member)
            if not item.isfile():
                raise ValueError("archive input must be a regular file")
            raw = archive.extractfile(item).read()
        record = {"basename": Path(member).name, "sha256": sha(raw),
                  "archive": record}
    return raw, record


def pdf_text(data, page=None):
    command = ["pdftotext", "-layout"]
    if page is not None:
        command += ["-f", str(page), "-l", str(page)]
    return subprocess.run(command + ["-", "-"], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True).stdout.decode("utf-8")


def unique_map(pairs, kind):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate " + kind + " name")
        result[name] = value
    if not result:
        raise ValueError("no " + kind + " entries")
    return result


def liberty_areas(text):
    # Remove comments before finding cell headers. Require an area attribute in
    # every cell's prefix before its first child group, rather than silently
    # skipping cells whose formatting differs from the usual area-first layout.
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    headers = list(re.finditer(r'\bcell\s*\(\s*"?([^\s()"]+)"?\s*\)\s*\{', text))
    pairs = []
    for index, match in enumerate(headers):
        limit = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        prefix = text[match.end():limit]
        boundary = prefix.find("{")
        prefix = prefix[:boundary] if boundary >= 0 else prefix
        area = re.search(r"\barea\s*:\s*(" + NUMBER + r")\s*;", prefix)
        if area is None:
            raise ValueError("Liberty cell has no top-level numeric area")
        pairs.append((match.group(1), Decimal(area.group(1))))
    return unique_map(pairs, "Liberty cell")


def lef_areas(text):
    text = re.sub(r"#[^\n]*", "", text)
    pairs = []
    macros = list(re.finditer(r"^\s*MACRO\s+(\S+)\s*$", text, re.M))
    for index, match in enumerate(macros):
        limit = macros[index + 1].start() if index + 1 < len(macros) else len(text)
        tail = text[match.end():limit]
        end = re.search(r"^\s*END\s+" + re.escape(match.group(1)) + r"\s*$", tail, re.M)
        if end is None:
            raise ValueError("unterminated LEF macro")
        size = re.search(r"\bSIZE\s+(" + NUMBER + r")\s+BY\s+(" + NUMBER + r")\s*;", tail[:end.start()])
        if size is None:
            raise ValueError("LEF macro has no SIZE")
        pairs.append((match.group(1), Decimal(size.group(1)) * Decimal(size.group(2))))
    return unique_map(pairs, "LEF macro")


def compare(left, right, absolute_tolerance=Decimal(0), relative_tolerance=Decimal(0)):
    common = left.keys() & right.keys()
    errors = [abs(left[name] - right[name]) for name in common]
    relative_errors = [abs(left[name] - right[name]) / abs(left[name]) for name in common if left[name] != 0]
    accepted = [abs(left[name] - right[name]) <= absolute_tolerance + relative_tolerance * abs(left[name]) for name in common]
    return {"left_entries": len(left), "right_entries": len(right),
            "compared": len(common), "exact_matches": sum(error == 0 for error in errors),
            "within_tolerance_matches": sum(accepted),
            "mismatches": sum(error != 0 for error in errors),
            "left_missing_on_right": len(left.keys() - right.keys()),
            "right_missing_on_left": len(right.keys() - left.keys()),
            "max_absolute_error": str(max(errors)) if errors else None,
            "max_relative_error_nonzero_reference": str(max(relative_errors)) if relative_errors else None,
            "absolute_tolerance": str(absolute_tolerance), "relative_tolerance": str(relative_tolerance),
            "acceptance_rule": "abs(reference-observed) <= absolute_tolerance + relative_tolerance*abs(reference)",
            "passed": bool(left) and not (left.keys() - right.keys()) and all(accepted)}


def compatibility(data, lib_version, lef_version):
    lines = pdf_text(data, 2).splitlines()
    result = {"passed": False, "document_page": 2,
              "library_release": lib_version, "required_lef_kit": lef_version}
    for index, line in enumerate(lines):
        columns = line.split()
        if columns[:4] != ["Version", "rln", "ccs", "doc"]:
            continue
        for row in lines[index + 1:]:
            values = row.split()
            if len(values) != len(columns):
                continue
            if values[0] == lib_version:
                mapping = dict(zip(columns, values))
                result["matched_kits"] = {name: mapping[name] for name in ("nldm", "sef", "doc")}
                result["passed"] = mapping["nldm"] == lib_version and mapping["sef"] == lef_version
                return result
    return result


def dc_areas(text):
    pairs = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if fields[0] in ("cell", "cell_name", "name"):
            continue
        if len(fields) != 2 or not re.fullmatch(NUMBER, fields[1]):
            raise ValueError("DC area TSV must contain name and numeric area only")
        pairs.append((fields[0].rsplit("/", 1)[-1], Decimal(fields[1])))
    return unique_map(pairs, "DC library cell")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lib", required=True, help="private Liberty file")
    parser.add_argument("--lef", required=True, help="private LEF file or tar archive")
    parser.add_argument("--lef-member", help="exact LEF member when --lef is an archive")
    parser.add_argument("--release-note", help="private release PDF or tar archive")
    parser.add_argument("--release-note-member")
    parser.add_argument("--lib-kit-version")
    parser.add_argument("--lef-kit-version")
    parser.add_argument("--db", help="actual synthesis DB; hashed without an EDA tool")
    parser.add_argument("--dc-area", help="private name/area TSV from the actual DC DB readback")
    parser.add_argument("--dc-absolute-tolerance", type=Decimal, default=Decimal(0))
    parser.add_argument("--dc-relative-tolerance", type=Decimal, default=Decimal(0))
    parser.add_argument("--lef-reference", help="optional local copy of the pinned public LEF manual")
    parser.add_argument("--out", type=Path, default=ROOT / "evidence/core/area_units.json")
    args = parser.parse_args()
    if (not args.dc_absolute_tolerance.is_finite() or not args.dc_relative_tolerance.is_finite()
            or args.dc_absolute_tolerance < 0 or args.dc_relative_tolerance < 0):
        parser.error("DC numeric tolerances must be finite and nonnegative")
    tracked = {Path(__file__).resolve(): sha(Path(__file__).read_bytes())}
    inputs = {}
    lib, inputs["liberty"] = read_input(args.lib, None, tracked)
    lef, inputs["lef"] = read_input(args.lef, args.lef_member, tracked)
    lib_values, lef_values = liberty_areas(lib.decode()), lef_areas(lef.decode())
    cross = compare(lib_values, lef_values)
    if args.lef_reference:
        reference, _ = read_input(args.lef_reference, None, tracked)
    else:
        reference = urllib.request.urlopen(REFERENCE_URL, timeout=30).read()
    if sha(reference) != REFERENCE_SHA256:
        raise ValueError("public LEF reference changed; review before accepting")
    reference_text = " ".join(pdf_text(reference, 183).split())
    reference_passed = bool(re.search(r"SIZE width BY height\s+Specifies a placement bounding rectangle, in microns, for the\s+macro", reference_text))
    reference_record = {"title": "LEF/DEF 5.7 Language Reference", "author": "Cadence Design Systems",
                        "version": "5.7", "date": "November 2009", "pdf_page": 183,
                        "url": REFERENCE_URL, "sha256": sha(reference), "bytes": len(reference),
                        "macro_size_unit": "um", "definition_checked": reference_passed}
    kit = {"passed": False, "status": "NOT_CHECKED"}
    if args.release_note:
        if not args.lib_kit_version or not args.lef_kit_version:
            parser.error("--release-note requires both kit versions")
        release, inputs["release_note"] = read_input(args.release_note, args.release_note_member, tracked)
        kit = compatibility(release, args.lib_kit_version, args.lef_kit_version)
    database_sha = None
    dc_match = {"passed": False, "status": "NOT_CHECKED"}
    if args.db:
        _, inputs["dc_database"] = read_input(args.db, None, tracked)
        database_sha = inputs["dc_database"]["sha256"]
    if args.dc_area:
        if not args.db:
            parser.error("--dc-area requires --db for explicit database association")
        dc, inputs["dc_cell_areas"] = read_input(args.dc_area, None, tracked)
        dc_match = compare(lib_values, dc_areas(dc.decode()), args.dc_absolute_tolerance, args.dc_relative_tolerance)
        # Both sets must match when connecting Liberty units to the actual DB.
        dc_match["passed"] &= dc_match["right_missing_on_left"] == 0
    unit_passed = cross["passed"] and reference_passed and kit["passed"]
    passed = unit_passed and dc_match["passed"] and database_sha is not None
    for path, digest in tracked.items():
        if sha(path.read_bytes()) != digest:
            raise RuntimeError("an input changed during checking")
    output = {"schema_version": 1, "status": "VERIFIED" if passed else "INCOMPLETE",
              "passed": passed, "source_sha256": {str(Path(__file__).resolve().relative_to(ROOT)): tracked[Path(__file__).resolve()]},
              "inputs": inputs, "method": "Exact Decimal equality of every Liberty cell area with the same-name LEF MACRO SIZE width times height; optional comparison with all actual DC DB library cell areas using explicit numeric tolerances (default zero). No per-cell values are published.",
              "liberty_lef_match": cross, "lef_reference": reference_record,
              "kit_compatibility": kit, "liberty_area_unit_verified": unit_passed,
              "area_unit": "um2" if unit_passed else "UNVERIFIED",
              "dc_database_sha256": database_sha, "dc_cell_area_match": dc_match,
              "limitations": ["The DC TSV association must be checked against the independent synthesis readback receipt and database hash.",
                              "Cell footprint area does not establish placed core/die area, timing closure, power, or physical signoff.",
                              "The supplier input files and per-cell geometric/numeric data remain private."]}
    if args.out.resolve() in tracked:
        raise ValueError("output cannot overwrite an input")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"status": output["status"], "liberty_lef_cells": cross["compared"],
                      "liberty_lef_matches": cross["exact_matches"], "unit": output["area_unit"],
                      "dc_match_passed": dc_match["passed"]}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
