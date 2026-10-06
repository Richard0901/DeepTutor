#!/usr/bin/env python3
"""Import case JSON files into the central teaching database.

Examples::

    # Import the bundled synthetic seed cases (10 cases, L1-L4)
    python scripts/import_clinical_cases.py deeptutor/clinical/seed_cases

    # Import a directory of expert-authored cases under a specific tenant
    python scripts/import_clinical_cases.py /path/to/cases --tenant hospital-x

    # Emit the import template for case authors
    python scripts/import_clinical_cases.py --emit-template ./template_out

The database defaults to ``<runtime-home>/data/system/clinical_learning.db``
and can be overridden with ``DEEPTUTOR_TEACHING_DB``.  A batch import never
stops at the first invalid file — every file is validated and the summary
lists each failure so a whole batch can be corrected in one pass.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from deeptutor.clinical.case_import import import_directory, write_case_template  # noqa: E402
from deeptutor.teaching.database import connect, migrate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        help="directory containing case *.json files",
    )
    parser.add_argument("--tenant", default="default", help="tenant_id to import under")
    parser.add_argument("--actor", default="case-import", help="actor id recorded as creator")
    parser.add_argument(
        "--emit-template",
        type=Path,
        metavar="DIR",
        help="write the case import template into DIR and exit",
    )
    args = parser.parse_args()

    if args.emit_template is not None:
        path = write_case_template(args.emit_template)
        print(f"template written: {path}")
        return 0

    if args.directory is None:
        parser.error("a case directory is required (or use --emit-template)")
    if not args.directory.is_dir():
        print(f"not a directory: {args.directory}", file=sys.stderr)
        return 1

    conn = connect()
    try:
        migrate(conn)
        report = import_directory(conn, args.directory, tenant_id=args.tenant, actor_id=args.actor)
    finally:
        conn.close()
    print(report.summary())
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
