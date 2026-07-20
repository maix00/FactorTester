#!/usr/bin/env python3
"""Validate one bounded paired AdjudicationProposal JSON file."""

from __future__ import annotations

import argparse
import json
import sys

from _proposal_validation import (
    load_payload,
    result,
    validate_adjudication,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        value = validate_adjudication(load_payload(args.input))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        return 1
    print(json.dumps(result(value, kind="adjudication_proposal")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
