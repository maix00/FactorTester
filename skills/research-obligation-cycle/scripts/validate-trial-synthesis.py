#!/usr/bin/env python3
"""Validate one selective TrialPlan-synthesis output."""

from __future__ import annotations

import argparse
import json
import sys

from _proposal_validation import load_payload
from _trial_synthesis_validation import (
    validate_trial_synthesis,
    validation_result,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        value = validate_trial_synthesis(load_payload(args.input))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        return 1
    print(json.dumps(validation_result(value)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
