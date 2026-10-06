# src/palatium_ai/domain/memory/binary_quantize.py

"""Binary quantization helpers for memory@4096 (Wave M8 / 060).

pgvector float HNSW maxes at 2000 dims; native 4096 uses exact cosine or
optional ``bit(4096)`` HNSW + float rerank. These helpers are pure and
eval-gated — enable only behind ``MEMORY_BINARY_QUANTIZE_RERANK``.
"""

from __future__ import annotations

from collections.abc import Sequence


def binary_quantize(vector: Sequence[float]) -> bytes:
    """Pack sign bits (positive → 1) into little-endian bytes."""
    if not vector:
        msg = "vector must be non-empty"
        raise ValueError(msg)
    bits = 0
    out = bytearray()
    for idx, value in enumerate(vector):
        if float(value) > 0.0:
            bits |= 1 << (idx % 8)
        if idx % 8 == 7:
            out.append(bits)
            bits = 0
    if len(vector) % 8:
        out.append(bits)
    return bytes(out)


def hamming_distance(left: bytes, right: bytes) -> int:
    """Bit population count of XOR; pads the shorter operand with zeros."""
    n = max(len(left), len(right))
    a = left.ljust(n, b"\x00")
    b = right.ljust(n, b"\x00")
    return sum((x ^ y).bit_count() for x, y in zip(a, b, strict=True))


def hamming_similarity(left: bytes, right: bytes, *, bit_length: int | None = None) -> float:
    """``1 - hamming/bits`` in [0, 1]."""
    bits = bit_length if bit_length is not None else max(len(left), len(right)) * 8
    if bits <= 0:
        return 0.0
    distance = hamming_distance(left, right)
    return max(0.0, min(1.0, 1.0 - (distance / float(bits))))


def rank_by_hamming(
    query: Sequence[float],
    candidates: list[tuple[Sequence[float], dict[str, object]]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    """Order candidates by Hamming similarity of binary-quantized vectors."""
    q_bits = binary_quantize(query)
    bit_len = len(query)
    scored: list[tuple[float, dict[str, object]]] = []
    for vec, payload in candidates:
        sim = hamming_similarity(q_bits, binary_quantize(vec), bit_length=bit_len)
        enriched = dict(payload)
        enriched["_hamming"] = round(sim, 4)
        scored.append((sim, enriched))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[: max(1, limit)]]
