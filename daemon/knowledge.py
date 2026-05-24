import os
import re
import math
from collections import Counter
from typing import List, Dict, Tuple, Set

class KnowledgeBase:
    def __init__(self, file_paths: List[str] = None):
        """
        Initialize and load the knowledge base from a list of text/markdown files.
        """
        self.file_paths = file_paths or []
        self.chunks: List[Dict] = []  # List of dicts: {"file": str, "text": str, "tokens": List[str]}
        self.vocab: Set[str] = set()
        self.idf: Dict[str, float] = {}
        self.chunk_tfidf_vectors: List[Dict[str, float]] = []
        self.file_chunk_counts: Dict[str, int] = {}
        
        self._load_and_process()

    def _load_and_process(self):
        """
        Load files, chunk them, tokenize, and pre-compute TF-IDF models.
        """
        for path in self.file_paths:
            if not os.path.exists(path):
                print(f"Warning: Knowledge base file not found: {path}")
                continue
            
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"Error reading knowledge file {path}: {e}")
                continue
            
            filename = os.path.basename(path)
            file_chunks = self._chunk_text(content)
            self.file_chunk_counts[filename] = len(file_chunks)
            
            for chunk_text in file_chunks:
                tokens = self._tokenize(chunk_text)
                if tokens:
                    self.chunks.append({
                        "file": filename,
                        "text": chunk_text,
                        "tokens": tokens
                    })
                    for t in tokens:
                        self.vocab.add(t)

        if not self.chunks:
            return

        # Precompute IDF
        total_docs = len(self.chunks)
        doc_frequencies = Counter()
        for chunk in self.chunks:
            unique_tokens = set(chunk["tokens"])
            for t in unique_tokens:
                doc_frequencies[t] += 1
        
        for term, df in doc_frequencies.items():
            # Standard TF-IDF IDF formula with smoothing to avoid division by zero
            self.idf[term] = math.log((1 + total_docs) / (1 + df)) + 1.0

        # Precompute TF-IDF vectors for each chunk
        for chunk in self.chunks:
            tf_vector = Counter(chunk["tokens"])
            total_tokens = len(chunk["tokens"])
            tfidf_vector = {}
            for term, count in tf_vector.items():
                tf = count / total_tokens
                tfidf_vector[term] = tf * self.idf.get(term, 0.0)
            self.chunk_tfidf_vectors.append(tfidf_vector)

    def _chunk_text(self, text: str, max_words: int = 500, min_words: int = 80) -> List[str]:
        """
        Chunks text by paragraphs, merging short ones and splitting extremely long ones.
        """
        # Split by empty lines
        raw_paragraphs = re.split(r'\n\s*\n', text)
        paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
        
        chunks = []
        current_chunk = []
        current_word_count = 0
        
        for p in paragraphs:
            p_words = p.split()
            p_word_count = len(p_words)
            
            # If a single paragraph is huge, split it
            if p_word_count > max_words:
                # If we have an ongoing chunk, save it first
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_word_count = 0
                
                # Split huge paragraph into smaller sub-chunks
                for i in range(0, p_word_count, max_words):
                    sub_p = " ".join(p_words[i:i + max_words])
                    chunks.append(sub_p)
                continue

            # Check if adding this paragraph exceeds max_words
            if current_word_count + p_word_count > max_words:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = [p]
                current_word_count = p_word_count
            else:
                current_chunk.append(p)
                current_word_count += p_word_count
                
                # If we've reached a decent size, we can close the chunk,
                # but let's keep packing unless it exceeds max_words.
                if current_word_count >= min_words:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_word_count = 0

        # Add remaining text
        if current_chunk:
            chunks.append("\n\n".join(current_chunk))
            
        return [c for c in chunks if c.strip()]

    def _tokenize(self, text: str) -> List[str]:
        """
        Basic lowercase word tokenization.
        """
        return re.findall(r'\b\w{2,}\b', text.lower())

    def search(self, query: str, top_k: int = 3) -> str:
        """
        Search the knowledge base for relevant chunks matching the query using TF-IDF similarity.
        Returns a single concatenated string of the top-k chunks.
        """
        if not self.chunks or not query.strip():
            return ""

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return ""

        # Calculate TF-IDF for query
        query_tf = Counter(query_tokens)
        query_len = len(query_tokens)
        query_tfidf = {}
        for term, count in query_tf.items():
            if term in self.vocab:
                tf = count / query_len
                query_tfidf[term] = tf * self.idf.get(term, 0.0)

        if not query_tfidf:
            return ""

        # Calculate cosine similarity with all chunks
        similarities: List[Tuple[float, Dict]] = []
        query_norm = math.sqrt(sum(v ** 2 for v in query_tfidf.values()))
        
        for idx, chunk_vector in enumerate(self.chunk_tfidf_vectors):
            # Calculate dot product
            dot_product = sum(query_tfidf[term] * chunk_vector.get(term, 0.0) for term in query_tfidf)
            if dot_product == 0.0:
                continue
            
            chunk_norm = math.sqrt(sum(v ** 2 for v in chunk_vector.values()))
            similarity = dot_product / (query_norm * chunk_norm)
            similarities.append((similarity, self.chunks[idx]))

        # Sort by similarity descending
        similarities.sort(key=lambda x: x[0], reverse=True)
        top_results = similarities[:top_k]

        if not top_results:
            return ""

        output_chunks = []
        for sim, chunk in top_results:
            source_info = f"[Source: {chunk['file']}]"
            output_chunks.append(f"{source_info}\n{chunk['text']}")

        return "\n\n---\n\n".join(output_chunks)

    def get_file_summary(self) -> str:
        """
        Return a summary of loaded files and chunk counts.
        """
        if not self.file_chunk_counts:
            return "No knowledge base files loaded."
        
        summary_lines = ["Loaded knowledge files:"]
        for filename, count in self.file_chunk_counts.items():
            summary_lines.append(f"- {filename} ({count} chunks)")
        return "\n".join(summary_lines)
