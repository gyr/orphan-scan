"""Shared pytest fixtures (fake_config, fake_runner, fixture-data loaders).

Populated incrementally as each feature module is implemented.
"""

from __future__ import annotations

import io
import tarfile


def make_tar(filename: str, data: bytes) -> bytes:
    """Return bytes of a tar archive containing one file."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tf:
        info = tarfile.TarInfo(name=filename)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()
