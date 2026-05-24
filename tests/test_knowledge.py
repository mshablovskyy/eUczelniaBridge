import os
import tempfile
import pytest
from daemon.knowledge import KnowledgeBase


@pytest.fixture
def temp_files() -> tuple[str, str]:
    # Create two temporary text files
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".md", delete=False, encoding="utf-8") as f1:
        f1.write("# Python Guide\n\nPython is a programming language. It is easy to learn and read.")
        f1.flush()
        path1 = f1.name

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False, encoding="utf-8") as f2:
        f2.write("Moodle is a learning platform.\n\nIt is used in universities worldwide.")
        f2.flush()
        path2 = f2.name

    yield path1, path2

    os.remove(path1)
    os.remove(path2)


def test_knowledge_base_loading(temp_files: tuple[str, str]) -> None:
    path1, path2 = temp_files
    kb = KnowledgeBase([path1, path2])

    assert len(kb.chunks) == 2  # Small paragraphs are merged per file
    assert kb.file_chunk_counts[os.path.basename(path1)] == 1  # Head + body is merged because they are small
    assert kb.file_chunk_counts[os.path.basename(path2)] == 1  # Head + body is merged because they are small

    # vocab check
    assert "python" in kb.vocab
    assert "moodle" in kb.vocab


def test_knowledge_base_search(temp_files: tuple[str, str]) -> None:
    path1, path2 = temp_files
    kb = KnowledgeBase([path1, path2])

    # Search for python
    res_py = kb.search("What is Python?", top_k=1)
    assert "Python is a programming language" in res_py
    assert f"[Source: {os.path.basename(path1)}]" in res_py

    # Search for Moodle
    res_moodle = kb.search("Moodle platforms", top_k=1)
    assert "Moodle is a learning platform" in res_moodle
    assert f"[Source: {os.path.basename(path2)}]" in res_moodle


def test_knowledge_base_empty() -> None:
    kb = KnowledgeBase([])
    assert kb.search("anything") == ""
    assert "No knowledge base files loaded" in kb.get_file_summary()


def test_knowledge_base_file_not_found() -> None:
    kb = KnowledgeBase(["non_existent_file.txt"])
    assert len(kb.chunks) == 0
    assert kb.search("anything") == ""
    assert "No knowledge base files loaded" in kb.get_file_summary()


def test_get_file_summary(temp_files: tuple[str, str]) -> None:
    path1, path2 = temp_files
    kb = KnowledgeBase([path1, path2])
    summary = kb.get_file_summary()

    assert "Loaded knowledge files:" in summary
    assert os.path.basename(path1) in summary
    assert os.path.basename(path2) in summary


def test_chunking_large_paragraphs() -> None:
    # Test that very long paragraph is split into multiple chunks
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False, encoding="utf-8") as f:
        # Paragraph with 600 words of "word"
        long_para = " ".join(["word"] * 600)
        f.write(long_para)
        f.flush()
        path = f.name

    try:
        kb = KnowledgeBase([path])
        # Since max_words defaults to 500, it should split into 2 chunks (500 + 100)
        assert len(kb.chunks) == 2
    finally:
        os.remove(path)
