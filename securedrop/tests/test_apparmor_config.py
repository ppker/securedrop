"""Tests for AppArmor configuration completeness."""

import os
import re
from pathlib import Path


def test_apparmor_config():
    """
    Verify that the set of Python files in securedrop/ exactly matches the set
    of Python files listed in the AppArmor configuration file. This ensures:
    1. All application code has proper AppArmor permissions when running under Apache
    2. The AppArmor config doesn't have stale entries for deleted files
    """
    # Files/directories that don't run under Apache and should be exempted
    EXEMPTIONS = {
        # Database migrations run via management commands, not Apache
        "alembic/",
        # Management commands run separately, not via Apache
        "management/",
        # Developer/test scripts that don't run under Apache
        "loaddata.py",
        "loadfixeddata.py",
        "manage.py",
        "setup.py",
        "specialstrings.py",
        "upload-screenshots.py",
    }

    # Find all Python files in securedrop/ directory (excluding tests and debian)
    securedrop_dir = Path(__file__).parent.parent
    expected_python_files = set()

    for root, dirs, files in os.walk(securedrop_dir):
        # Skip hidden directories, __pycache__, and debian directory
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "debian")]

        # Also skip the tests directory itself - tests don't run under Apache
        relative_root = Path(root).relative_to(securedrop_dir)
        if relative_root.parts and relative_root.parts[0] == "tests":
            continue

        for file in files:
            if file.endswith(".py"):
                # Get the path relative to securedrop/
                full_path = Path(root) / file
                rel_path = full_path.relative_to(securedrop_dir)
                rel_path_str = str(rel_path)

                # Check if this file matches any exemption
                is_exempted = False
                for exemption in EXEMPTIONS:
                    if exemption.endswith("/"):
                        # Directory exemption
                        if rel_path_str.startswith(exemption):
                            is_exempted = True
                            break
                    # File exemption
                    elif rel_path_str == exemption:
                        is_exempted = True
                        break

                if not is_exempted:
                    expected_python_files.add(rel_path_str)

    # Extract Python file paths from AppArmor config
    # Look for lines like: /var/www/securedrop/path/to/file.py r
    actual_python_files = set()
    python_file_pattern = re.compile(r"^\s*/var/www/securedrop/(.*\.py)\s+r\s*,?\s*$")

    apparmor_config = (
        Path(__file__).parent.parent / "debian/app-code/etc/apparmor.d/usr.sbin.apache2"
    ).read_text()

    for line in apparmor_config.splitlines():
        match = python_file_pattern.match(line)
        if match:
            py_file = match.group(1)
            actual_python_files.add(py_file)

    assert expected_python_files == actual_python_files
