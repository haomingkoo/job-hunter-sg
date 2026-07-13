"""One-shot resource-limited worker for untrusted resume files."""

from __future__ import annotations

import json
import sys

ADDRESS_SPACE_BYTES = 256 * 1024 * 1024
CPU_SECONDS = 5
MAX_INPUT_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024


def _apply_limits() -> None:
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows has no resource module
        return

    limits = {
        "RLIMIT_AS": ADDRESS_SPACE_BYTES,
        "RLIMIT_CPU": CPU_SECONDS,
        "RLIMIT_FSIZE": MAX_OUTPUT_BYTES,
        "RLIMIT_CORE": 0,
    }
    for name, requested in limits.items():
        if not hasattr(resource, name):
            continue
        limit = getattr(resource, name)
        try:
            _, hard = resource.getrlimit(limit)
            value = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
            resource.setrlimit(limit, (value, value))
        except (OSError, ValueError):
            pass


def _write(response: dict) -> None:
    payload = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payload) > MAX_OUTPUT_BYTES:
        payload = b'{"ok":false,"error":"Parsed resume output is too large."}'
    sys.stdout.buffer.write(payload)


def main() -> None:
    _apply_limits()
    header_bytes = sys.stdin.buffer.readline(16 * 1024)
    if not header_bytes.endswith(b"\n"):
        _write({"ok": False, "error": "Could not safely parse this resume."})
        return

    try:
        header = json.loads(header_bytes)
        size = int(header["size"])
        if size < 1 or size > MAX_INPUT_BYTES:
            raise ValueError
        file_bytes = sys.stdin.buffer.read(size + 1)
        if len(file_bytes) != size:
            raise ValueError
        from resume_parser import parse_resume

        result = parse_resume(
            filename=str(header["filename"]),
            content_type=str(header["content_type"]),
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        message = str(exc)
        _write({"ok": False, "error": message if len(message) <= 500 else "Could not safely parse this resume."})
    except Exception:
        _write({"ok": False, "error": "Could not safely parse this resume."})
    else:
        _write({"ok": True, "result": result})


if __name__ == "__main__":
    main()
