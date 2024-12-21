#!/usr/bin/env python3
"""
A simple script to test the ExecuteThreadManager + Executor classes.

Usage:
  python some_script.py --encoded-args "BASE64_ENCODED_JSON"

Example:
  python some_script.py --encoded-args "eyJrZXkiOiAidmFsdWUifQ=="
This script will decode the base64 and print it out.
"""

import sys
import json
import base64
import time

# Optional special markers for returning structured data
OUTPUT_PREFIX = "##BEGIN_ENCODED_OUTPUT##"
OUTPUT_SUFFIX = "##END_ENCODED_OUTPUT##"

def main():
    # default to empty dict if no args found
    decoded_args = {}

    # A simple approach to parse `--encoded-args <encoded_string>`
    for i, arg in enumerate(sys.argv):
        if arg == "--encoded-args" and i + 1 < len(sys.argv):
            encoded_str = sys.argv[i + 1]
            try:
                json_str = base64.b64decode(encoded_str).decode("utf-8")
                decoded_args = json.loads(json_str)
            except Exception as e:
                print(f"Failed to decode/parse args: {e}")
            break

    print("=== some_script.py START ===")
    print("Received decoded arguments:", decoded_args)

    # Simulate some small "work" so we see real-time logging
    time.sleep(2)  # e.g. 2 seconds of "work"

    # Let's say we produce a result dictionary
    result_data = {
        "status": "success",
        "echo_args": decoded_args,
        "message": "Hello from some_script.py!"
    }

    # Print the special output block
    # This is optional, but if you want the manager to parse something,
    # you can enclose it in these markers:
    encoded_output_json = base64.b64encode(json.dumps(result_data).encode("utf-8")).decode("utf-8")
    print(f"{OUTPUT_PREFIX}{encoded_output_json}{OUTPUT_SUFFIX}")

    print("=== some_script.py END ===")

if __name__ == "__main__":
    main()
