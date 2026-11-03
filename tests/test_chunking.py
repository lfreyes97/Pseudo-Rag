import random
import re

import pytest

from pseudo_rag.chunking import (CHUNKER_VERSION, _split_long, chunk_lines,
                                 params_signature)


def _lines(n, width=40, seed=1):
    rnd = random.Random(seed)
    return ["".join(rnd.choice("abcdefghij ") for _ in range(rnd.randint(0, width))) for _ in range(n)]


def test_empty_and_blank_inputs():
    assert chunk_lines([]) == []
    assert chunk_lines(["", "   ", ""]) == []
    c = chunk_lines(["x"])
    assert [(k.start, k.end, k.text) for k in c] == [(1, 1, "x")]


def test_invalid_params():
    with pytest.raises(ValueError):
        chunk_lines(["x"], max_chars=10)
    with pytest.raises(ValueError):
        chunk_lines(["x"], overlap=-1)


@pytest.mark.parametrize("max_chars,overlap", [(100, 0), (100, 2), (300, 3), (1000, 2)])
def test_max_size_respected(max_chars, overlap):
    for k in chunk_lines(_lines(400, width=90), max_chars=max_chars, overlap=overlap):
        assert len(k.text) <= max_chars


def test_text_is_exactly_the_lines_of_its_range():
    """Invariante: sin líneas largas, el texto del chunk == líneas[start-1:end] (contiguo)."""
    lines = _lines(300, width=60)
    for k in chunk_lines(lines, max_chars=200, overlap=3):
        assert k.text == "\n".join(lines[k.start - 1:k.end])


def test_every_nonblank_line_is_covered():
    lines = _lines(500, width=80)
    cov = set()
    for k in chunk_lines(lines, max_chars=250, overlap=2):
        cov.update(range(k.start, k.end + 1))
    assert all((i + 1) in cov for i, l in enumerate(lines) if l.strip())


def test_chunks_always_advance_and_terminate():
    cases = [["a" * 5000] * 20, [""] * 50, ["x"] * 200, _lines(200, 5), ["= H"] * 100]
    for lines in cases:
        c = chunk_lines(lines, max_chars=120, overlap=5)
        for prev, cur in zip(c, c[1:]):
            assert cur.start >= prev.start and cur.end >= prev.end
            assert (cur.start, cur.end) != (prev.start, prev.end) or len(lines[prev.start - 1]) > 120


def test_overlap_shares_lines_and_zero_means_none():
    lines = [f"linea numero {i:03d}" for i in range(60)]
    with_ov = chunk_lines(lines, max_chars=150, overlap=2)
    assert all(b.start <= a.end for a, b in zip(with_ov, with_ov[1:]))
    no_ov = chunk_lines(lines, max_chars=150, overlap=0)
    assert all(b.start == a.end + 1 for a, b in zip(no_ov, no_ov[1:]))


def test_overlap_never_exceeds_budget_or_pushes_chunk_over_max():
    lines = ["x" * 90] * 30
    for k in chunk_lines(lines, max_chars=200, overlap=5):
        assert len(k.text) <= 200


def test_heading_starts_a_new_chunk_when_current_is_big_enough():
    body = ["texto de relleno " * 3] * 5       # ~260 caracteres
    lines = body + ["== Nueva sección", "contenido"]
    c = chunk_lines(lines, max_chars=500, overlap=0)
    assert len(c) == 2 and c[1].text.startswith("== Nueva sección")


def test_small_chunk_is_not_cut_at_heading():
    c = chunk_lines(["= A", "x", "== B", "y"], max_chars=1000, overlap=0)
    assert len(c) == 1


def test_markdown_heading_also_cuts():
    lines = ["relleno " * 20] * 3 + ["# Título", "texto"]
    c = chunk_lines(lines, max_chars=400, overlap=0)
    assert any(k.text.startswith("# Título") for k in c)


def test_long_line_is_split_by_sentences_keeping_line_number():
    sent = "Esta es una frase de prueba bastante larga para el test. "
    line = (sent * 40).strip()  # ~2300 caracteres
    c = chunk_lines(["antes", line, "despues"], max_chars=500, overlap=0)
    assert all(len(k.text) <= 500 for k in c)
    # los trozos de la línea larga siguen apuntando a la línea 2
    assert len([k for k in c if k.start <= 2 <= k.end]) >= 4
    assert any(k.start == k.end == 2 for k in c)
    # no se pierde ni se duplica contenido
    norm = lambda t: re.sub(r"\s+", " ", t)
    assert norm(" ".join(k.text for k in c)) == norm("antes " + line + " despues")


def test_long_line_without_spaces_is_hard_split():
    pieces = _split_long("x" * 2500, 1000)
    assert [len(p) for p in pieces] == [1000, 1000, 500]


def test_split_long_preserves_content_and_limit():
    text = "Hola mundo. " * 300 + "fin"
    parts = _split_long(text, 200)
    assert all(len(p) <= 200 for p in parts)
    assert re.sub(r"\s+", "", "".join(parts)) == re.sub(r"\s+", "", text)


def test_params_signature_is_versioned():
    assert params_signature(1000, 2) == f"v{CHUNKER_VERSION}:1000:2"
    assert params_signature(1000, 2) != params_signature(500, 2) != params_signature(500, 0)
