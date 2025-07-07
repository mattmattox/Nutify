#!/usr/bin/env python3
"""
Test parser for UPS notifier

This script tests the parse_input_args function from ups_notifier.py with various message formats
"""

import sys
import os
from pathlib import Path

# Add the application directory to sys.path to allow imports
APP_DIR = str(Path(__file__).resolve().parent.parent.parent)
if APP_DIR not in sys.path:
    sys.path.append(APP_DIR)

from core.events.ups_notifier import parse_input_args

def main():
    """Main test function"""
    # Standard format tests
    standard_tests = [
        'ups@localhost ONLINE',
        'ups@localhost ONBATT',
        'ups@localhost LOWBATT',
        'ups@localhost FSD',
        'ups@localhost COMMOK',
        'ups@localhost COMMBAD',
        'ups@localhost SHUTDOWN',
        'ups@localhost REPLBATT',
        'ups@localhost NOCOMM',
        'ups@localhost NOPARENT'
    ]

    # Message format tests
    message_tests = [
        'UPS ups@localhost on battery',
        'UPS ups@localhost on line power',
        'UPS ups@localhost low battery',
        'UPS ups@localhost forced shutdown',
        'Communications restored with UPS ups@localhost',
        'Communications with UPS ups@localhost lost',
        'UPS ups@localhost shutdown in progress',
        'UPS ups@localhost battery needs replacing',
        'No communication with UPS ups@localhost',
        'Parent process died - shutting down UPS ups@localhost'
    ]

    print("\n=== Testing standard format (ups@host EVENT) ===")
    for test in standard_tests:
        result = parse_input_args([test])
        print(f"{test} -> {result}")

    print("\n=== Testing message formats ===")
    for test in message_tests:
        result = parse_input_args([test])
        print(f"{test} -> {result}")

    # Special case: Communications with UPS lost (the format that caused issues)
    print("\n=== Testing problematic format ===")
    result = parse_input_args(['Communications with UPS ups@127.0.0.1 lost'])
    print(f"Communications with UPS ups@127.0.0.1 lost -> {result}")

if __name__ == "__main__":
    main() 