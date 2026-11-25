"""JSON line protocol helpers for master ↔ worker."""

from .messages import MessageType, encode, decode, make

__all__ = ["MessageType", "encode", "decode", "make"]
