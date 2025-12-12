import boto3
import math
from typing import Optional, Tuple

BLOCK = 512

def _s3_get_range(s3, bucket: str, key: str, start: int, end_inclusive: int) -> bytes:
    resp = s3.get_object(
        Bucket=bucket,
        Key=key,
        Range=f"bytes={start}-{end_inclusive}",
        RequestPayer="requester",
    )
    return resp["Body"].read()

def _find_tar_header_offset(buf: bytes) -> Optional[int]:
    # Find "ustar" at header offset 257, scanning possible block alignments.
    # Tar headers should start at 512-byte boundaries within the tar stream,
    # but since our buffer is a window, we scan all alignments.
    n = len(buf)
    for off in range(0, n - BLOCK + 1):
        # only consider offsets that *could* be block boundaries in the real file
        # but we don't know real alignment, so accept all offsets and check magic.
        if off + 262 <= n and buf[off + 257: off + 262] == b"ustar":
            return off
    return None

def _parse_tar_size_from_header(header512: bytes) -> int:
    # size field: bytes 124..135 (12 bytes), octal ASCII, may include NUL/space
    raw = header512[124:136].split(b"\0", 1)[0].strip()
    if not raw:
        return 0
    return int(raw, 8)

def _aligned_down(x: int, a: int) -> int:
    return x - (x % a)

def _ceil_div(x: int, a: int) -> int:
    return (x + a - 1) // a

def fetch_tar_member_robust(
    bucket: str,
    key: str,
    bytes_start: int,
    bytes_end: int,
    *,
    requester_pays: bool = True,   # kept for parity; unused (always requester in helper)
    end_is_exclusive: bool = True,  # IMPORTANT: set based on your DB semantics
    pad: int = 2 * 1024 * 1024,     # 2MB window padding
    max_pad: int = 64 * 1024 * 1024 # cap padding escalation
) -> bytes:
    """
    Robustly fetch a tar member from an S3 tar bundle using approximate offsets.

    Returns: raw member bytes (the tar member payload, not including tar header).
    """
    s3 = boto3.client("s3")

    # Normalize end to inclusive
    end_incl = bytes_end - 1 if end_is_exclusive else bytes_end
    if end_incl < bytes_start:
        raise ValueError(f"bad range: start={bytes_start}, end={bytes_end} (excl={end_is_exclusive})")

    # We'll try increasing padding until we can locate + parse + fully fetch member.
    cur_pad = pad

    while True:
        # Download a window around start/end
        win_start = max(0, bytes_start - cur_pad)
        win_end   = end_incl + cur_pad

        buf = _s3_get_range(s3, bucket, key, win_start, win_end)

        hdr_off = _find_tar_header_offset(buf)
        if hdr_off is None:
            if cur_pad >= max_pad:
                raise RuntimeError("Could not find tar header (ustar) in padded window")
            cur_pad *= 2
            continue

        header = buf[hdr_off:hdr_off + BLOCK]
        size = _parse_tar_size_from_header(header)

        # Compute where this header sits in the real tar file
        real_header_pos = win_start + hdr_off

        # Tar payload is padded to 512-byte blocks
        payload_blocks = _ceil_div(size, BLOCK)
        payload_padded = payload_blocks * BLOCK

        member_start = real_header_pos + BLOCK
        member_end_incl = member_start + payload_padded - 1  # inclusive end of padded payload

        # Now fetch exact aligned span (header+payload) to avoid truncation
        exact_start = real_header_pos
        exact_end_incl = real_header_pos + BLOCK + payload_padded - 1

        exact = _s3_get_range(s3, bucket, key, exact_start, exact_end_incl)

        # Sanity check: should contain at least header+payload
        if len(exact) < BLOCK + size:
            if cur_pad >= max_pad:
                raise RuntimeError("Fetched exact span but still truncated")
            cur_pad *= 2
            continue

        payload = exact[BLOCK:BLOCK + size]  # strip tar padding
        return payload