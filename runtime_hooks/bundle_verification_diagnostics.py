import sys
from pathlib import Path


if "--verify-bundle" in sys.argv[1:]:
    try:
        error_stream = Path.cwd().joinpath(
            "autoocr-bundle-verification-error.log"
        ).open("a", encoding="utf-8", buffering=1)
    except OSError:
        pass
    else:
        sys.stdout = error_stream
        sys.stderr = error_stream
