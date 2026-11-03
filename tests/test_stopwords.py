from pseudo_rag.db import Database
from pseudo_rag.models import SearchRequest

q = Database._fts_query


def test_stopwords_are_dropped_in_english_and_spanish():
    assert q("Calvin and common grace") == '"Calvin" OR "common" OR "grace"'
    assert q("la gracia de Dios") == '"gracia" OR "Dios"'


def test_case_insensitive():
    assert q("The COVENANT") == '"COVENANT"'


def test_query_made_only_of_stopwords_keeps_them():
    assert q("the and of") == '"the" OR "and" OR "of"'


def test_empty_and_symbols_only():
    assert q("") == "" and q("¿?!") == ""


def test_stopword_does_not_match_unrelated_chunks(svc, tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("the cat and the dog\n\n" + "unrelated words here and there\n" * 1
                 + "\n\nzafiro azul\n", encoding="utf-8")
    svc.index_path(str(f), max_chars=60, overlap=0)
    r = svc.search(SearchRequest(query="zafiro and the", mode="text"))
    assert r.count == 1 and "zafiro" in r.results[0].text
