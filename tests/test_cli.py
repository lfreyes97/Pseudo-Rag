import json
import sys

import pytest

from pseudo_rag.cli import main


def run(capsys, *argv):
    rc = main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.delenv("PRAG_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_grep_exit_codes(capsys, in_tmp, docs):
    assert run(capsys, "grep", "-i", "pacto", str(docs), "--all-text")[0] == 0
    assert run(capsys, "grep", "zzzz", str(docs), "--all-text")[0] == 1
    rc, _, err = run(capsys, "grep", "(", str(docs), "-E", "--all-text")
    assert rc == 2 and "inválida" in err
    assert run(capsys, "grep", "x", str(docs / "no-existe"))[0] == 2


def test_grep_json_and_count(capsys, in_tmp, docs):
    rc, out, _ = run(capsys, "grep", "-i", "pacto", str(docs), "--all-text", "--json")
    data = json.loads(out)
    assert rc == 0 and data["ok"] and data["count"] == 2
    assert run(capsys, "grep", "-i", "pacto", str(docs), "--all-text", "-c")[1].strip() == "2"


def test_grep_jsonl_one_object_per_line(capsys, in_tmp, docs):
    _, out, _ = run(capsys, "grep", "-i", "pacto", str(docs), "--all-text", "--jsonl")
    rows = [json.loads(line) for line in out.splitlines()]
    assert len(rows) == 2 and all("line_no" in r for r in rows)


def test_grep_context_prints_lines_not_tuples(capsys, in_tmp, docs):
    _, out, _ = run(capsys, "grep", "Abraham", str(docs / "a.md"), "-C", "1", "--no-color")
    assert "(" not in out and "El pacto de gracia" in out and "Cristo cumple" in out


def test_grep_does_not_import_heavy_deps(docs):
    """En un proceso limpio: `prag grep` no debe cargar SQLAlchemy ni Chroma."""
    import os
    import subprocess
    root = os.path.join(os.path.dirname(__file__), "..")
    code = ("import sys; from pseudo_rag.cli import main; "
            f"main(['grep','pacto',r'{docs}','--all-text']); "
            "bad=[m for m in ('sqlalchemy','chromadb','pydantic') if m in sys.modules]; "
            "print('HEAVY:'+','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert out.stdout.strip().splitlines()[-1] == "HEAVY:", out.stdout + out.stderr


def test_search_without_index_is_error(capsys, in_tmp):
    rc, _, err = run(capsys, "search", "algo")
    assert rc == 2 and "No hay índice" in err
    rc, out, _ = run(capsys, "search", "algo", "--json")
    assert rc == 2 and json.loads(out)["ok"] is False


def test_index_search_status_history_roundtrip(capsys, in_tmp, docs):
    rc, _, err = run(capsys, "index", str(docs), "--all-text", "--no-semantic")
    assert rc == 0 and (in_tmp / ".prag" / "search.db").exists()

    rc, out, _ = run(capsys, "index", str(docs), "--all-text", "--no-semantic", "--json")
    assert json.loads(out)["skipped"] == 2  # incremental

    rc, out, _ = run(capsys, "search", "covenant", "--mode", "text", "--json")
    data = json.loads(out)
    assert rc == 0 and data["count"] == 1 and data["results"][0]["source"].endswith("b.txt")

    assert run(capsys, "search", "zzzzzz", "--mode", "text")[0] == 1

    rc, out, _ = run(capsys, "status", "--json")
    st = json.loads(out)
    assert st["documents"] == 2 and st["semantic_available"] in (True, False)

    rc, out, _ = run(capsys, "history", "--json")
    assert [h["query"] for h in json.loads(out)["history"]][:2] == ["zzzzzz", "covenant"]


def test_search_no_history_flag(capsys, in_tmp, docs):
    run(capsys, "index", str(docs), "--all-text", "--no-semantic")
    run(capsys, "search", "pacto", "--mode", "text", "--no-history")
    _, out, _ = run(capsys, "history", "--json")
    assert json.loads(out)["history"] == []


def test_semantic_mode_without_chroma_exit_2(capsys, in_tmp, docs):
    run(capsys, "index", str(docs), "--all-text", "--no-semantic")
    rc, _, err = run(capsys, "search", "x", "--mode", "semantic", "--no-semantic")
    assert rc == 2 and "chromadb" in err


def test_index_empty_dir_is_error(capsys, in_tmp):
    (in_tmp / "vacio").mkdir()
    assert run(capsys, "index", str(in_tmp / "vacio"), "--no-semantic")[0] == 2


def test_prag_home_env_is_used(capsys, in_tmp, docs, monkeypatch):
    home = in_tmp / "otro"
    monkeypatch.setenv("PRAG_HOME", str(home))
    run(capsys, "index", str(docs), "--all-text", "--no-semantic")
    assert (home / "search.db").exists() and not (in_tmp / ".prag").exists()
