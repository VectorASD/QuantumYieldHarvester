# This file has been moved to vm_decompiler/main.py
# and later split into multiple modules for easier development.
# Please use the new location for the latest code.
# This stub remains only to avoid breaking existing external links.

from pathlib import Path
import sys

if __name__ == "__main__":
    sys.path = [str(Path(__file__).resolve().parent.parent), *sys.path]
    from vm_decompiler.main import main
    main()
