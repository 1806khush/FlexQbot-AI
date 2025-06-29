from pinecone import Pinecone
from pinecone import ServerlessSpec
import requests
from bs4 import BeautifulSoup
import torch
import torch.nn.functional as F
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import numpy as np
from config import Configobj
from sentence_transformers.util import cos_sim
import re
import uuid
import time

class PineconeDocSearchBot:
    def __init__(self, api_key: Optional[str] = None, environment: Optional[str] = None, index_name: Optional[str] = None):
        self.api_key = api_key or Configobj.PINECONE_API_KEY
        self.environment = environment or Configobj.PINECONE_ENVIRONMENT
        self.index_name = index_name or Configobj.PINECONE_INDEX_NAME
        
        # Initialize components
        self.pc = None
        self.index = None
        self.embedding_model = None
        self.session = None
        self._initialized = False
        self.min_score_threshold = 0.65
        self.optimal_score_range = (0.75, 0.95)

    def initialize(self) -> None:
        if not self._initialized:
            self.initialize_session()
            self.initialize_pinecone()
            self.load_embedding_model()
            self.connect_to_index()
            self._initialized = True

    def initialize_session(self) -> None:
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def initialize_pinecone(self) -> None:
        try:
            self.pc = Pinecone(api_key=self.api_key)
            print("Pinecone initialized successfully!")
        except Exception as e:
            print(f"Error initializing Pinecone: {e}")
            raise

    def load_embedding_model(self) -> None:
        try:
            self.embedding_model = SentenceTransformer(Configobj.EMBEDDING_MODEL_NAME, device=Configobj.EMBEDDING_MODEL_DEVICE)
            print("Embedding model loaded successfully!")
        except Exception as e:
            print(f"Error loading embedding model: {e}")
            raise

    def get_embedding(self, text: str) -> List[float]:
        return self.embedding_model.encode(text, convert_to_tensor=False).tolist()

    def connect_to_index(self) -> None:
        try:
            if self.index_name not in self.pc.list_indexes().names():
                print(f"Index '{self.index_name}' doesn't exist, creating...")
                self.pc.create_index(
                    name=self.index_name,
                    dimension=Configobj.EMBEDDING_DIMENSION,
                    metric="cosine",
                    spec=ServerlessSpec(
                        cloud="aws",
                        region="us-east-1"
                    )
                )
                time.sleep(30)
            
            self.index = self.pc.Index(self.index_name)
            print(f"Connected to Pinecone index '{self.index_name}' successfully!")
        except Exception as e:
            print(f"Error connecting to Pinecone index: {e}")
            raise


    def crawl_data(self, url: str, timeout: int = 30) -> Optional[str]:
        if not self._initialized:
            self.initialize()
            
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            
            # Get text and clean it
            text = soup.get_text(separator=' ', strip=True)
            text = re.sub(r'\s+', ' ', text).strip()
            
            return text if text else None
            
        except requests.exceptions.RequestException as e:
            print(f"Error crawling {url}: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error while crawling {url}: {e}")
            return None

    def chunk_text(self, text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
        if not text:
            return []
            
        # Use config values if not provided
        chunk_size = chunk_size or Configobj.CHUNK_SIZE
        overlap = overlap or Configobj.CHUNK_OVERLAP
            
        # Improved chunking strategy
        chunks = []
        sentences = re.split(r'(?<=[.!?])\s+', text)  # Split into sentences
        current_chunk = []
        current_length = 0
        
        for sentence in sentences:
            sentence_length = len(sentence.split())
            
            # If adding this sentence would exceed the chunk size (with some buffer)
            if current_length + sentence_length > chunk_size * 1.1 and current_chunk:
                # Join current chunk and add to chunks
                chunk = ' '.join(current_chunk).strip()
                if chunk:  # Only add non-empty chunks
                    chunks.append(chunk)
                
                # Start new chunk with overlap
                if overlap > 0 and chunks:
                    last_chunk = chunks[-1]
                    overlap_sentences = last_chunk.split()[-overlap*3:]  # Approximate overlap in words
                    current_chunk = [' '.join(overlap_sentences)]
                    current_length = len(current_chunk[0].split())
                else:
                    current_chunk = []
                    current_length = 0
            
            current_chunk.append(sentence)
            current_length += sentence_length
        
        # Add the last chunk if it exists
        if current_chunk:
            chunk = ' '.join(current_chunk).strip()
            if chunk:
                chunks.append(chunk)
        
        # If we didn't get any chunks (very short text), return the whole text
        if not chunks:
            chunks.append(text.strip())
            
        return chunks

    def crawl_url_to_pineconedb(self, url: str) -> str:
        if not self._initialized:
            self.initialize()
            
        if not url:
            return "Error: No URL provided"
            
        print(f"Crawling URL: {url}")
        
        try:
            # Get page content
            content = self.crawl_data(url)
            if not content:
                return f"Error: No content retrieved from {url}"
            
            # Chunk the content with improved chunking
            chunks = self.chunk_text(content)
            if not chunks:
                return f"Error: No valid chunks created from {url}"
            
            print(f"Processing {len(chunks)} chunks from {url}")
            
            # Prepare vectors for upsert with enhanced metadata
            vectors = []
            for i, chunk in enumerate(chunks):
                vector_id = str(uuid.uuid4())
                embedding = self.get_embedding(chunk)
                
                # Calculate chunk statistics
                word_count = len(chunk.split())
                sentence_count = len(re.findall(r'[.!?]+', chunk))
                avg_sentence_length = word_count / sentence_count if sentence_count > 0 else 0
                
                vectors.append({
                    "id": vector_id,
                    "values": embedding,
                    "metadata": {
                        "text": chunk,
                        "source_url": url,
                        "chunk_index": i,
                        "word_count": word_count,
                        "sentence_count": sentence_count,
                        "avg_sentence_length": avg_sentence_length,
                        "content_type": "text"  # Could be extended for other types
                    }
                })
            
            # Upsert in batches using config batch size
            batch_size = Configobj.BATCH_SIZE
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i:i + batch_size]
                self.index.upsert(vectors=batch)
                print(f"Upserted batch {i//batch_size + 1} of {len(vectors)//batch_size + 1}")
                time.sleep(1)  # Rate limiting
            
            return f"Successfully processed and stored {len(vectors)} chunks from {url}"
            
        except Exception as e:
            error_msg = f"Error processing {url}: {str(e)}"
            print(error_msg)
            return error_msg

    def crawl_multiple_urls(self, urls: List[str]) -> tuple:
        results = {}
        processed = 0
        failed = 0
        
        for url in urls:
            try:
                result = self.crawl_url_to_pineconedb(url)
                if "Successfully" in result:
                    processed += 1
                    results[url] = {"status": "success", "message": result}
                else:
                    failed += 1
                    results[url] = {"status": "failed", "message": result}
            except Exception as e:
                failed += 1
                results[url] = {"status": "error", "message": str(e)}
        
        summary = f"Processed {processed} URLs successfully, {failed} failed"
        return results, summary

    def search(self, query: str, top_k: int = 5, score_threshold: float = None) -> Dict:
        if not self._initialized:
            self.initialize()
            
        try:
            query_embedding = self.get_embedding(query)
            results = self.index.query(
                vector=query_embedding,
                top_k=top_k * 3,  # Get more results initially for filtering
                include_metadata=True
            )
            
            # Convert numpy types to native Python types and filter results
            results_dict = results.to_dict()
            
            # Apply score threshold filtering
            score_threshold = score_threshold or self.min_score_threshold
            filtered_matches = [
                match for match in results_dict['matches'] 
                if match['score'] >= score_threshold
            ]
            
            # Apply additional ranking based on chunk quality
            ranked_matches = sorted(
                filtered_matches,
                key=lambda x: (
                    x['score'],  # Primary sort by score
                    -x['metadata'].get('avg_sentence_length', 0),  # Prefer moderate sentence lengths
                    x['metadata'].get('word_count', 0)  # Prefer chunks with more words (but not too long)
                ),
                reverse=True
            )[:top_k]  # Take only the top_k after filtering
            
            # Replace matches with our filtered and ranked results
            results_dict['matches'] = ranked_matches
            
            # Add query embedding info
            results_dict['query_info'] = {
                'query_text': query,
                'query_embedding_length': len(query_embedding),
                'score_threshold_applied': score_threshold
            }
            
            # Recursively convert numpy types in the dictionary
            def convert_numpy_types(obj):
                if isinstance(obj, np.generic):
                    return obj.item()
                elif isinstance(obj, dict):
                    return {k: convert_numpy_types(v) for k, v in obj.items()}
                elif isinstance(obj, (list, tuple)):
                    return [convert_numpy_types(x) for x in obj]
                return obj
            
            return convert_numpy_types(results_dict)
            
        except Exception as e:
            print(f"Error during search: {e}")
            raise

    def calculate_semantic_similarity(self, text1: str, text2: str) -> float:
        """Calculate semantic similarity between two texts"""
        emb1 = self.get_embedding(text1)
        emb2 = self.get_embedding(text2)
        similarity = cos_sim(torch.tensor(emb1), torch.tensor(emb2)).item()
        return similarity

    def evaluate_chunk_quality(self, chunk: str) -> Dict:
        """Evaluate the quality of a text chunk for embedding"""
        words = chunk.split()
        sentences = re.split(r'(?<=[.!?])\s+', chunk)
        
        metrics = {
            'word_count': len(words),
            'sentence_count': len(sentences),
            'avg_sentence_length': len(words) / len(sentences) if sentences else 0,
            'lexical_diversity': len(set(words)) / len(words) if words else 0,
            'stopword_ratio': sum(1 for word in words if word.lower() in self.get_stopwords()) / len(words) if words else 0
        }
        
        # Score based on ideal ranges
        score = 0
        # Ideal word count between 50-200
        if 50 <= metrics['word_count'] <= 200:
            score += 0.3
        elif 30 <= metrics['word_count'] <= 300:
            score += 0.2
        else:
            score += 0.1
            
        # Ideal sentence count between 3-8
        if 3 <= metrics['sentence_count'] <= 8:
            score += 0.3
        elif 1 <= metrics['sentence_count'] <= 12:
            score += 0.2
        else:
            score += 0.1
            
        # Ideal avg sentence length between 15-25 words
        if 15 <= metrics['avg_sentence_length'] <= 25:
            score += 0.2
        elif 10 <= metrics['avg_sentence_length'] <= 30:
            score += 0.15
        else:
            score += 0.05
            
        # Higher lexical diversity is better
        score += metrics['lexical_diversity'] * 0.1
        
        # Moderate stopword ratio is best (0.2-0.4)
        if 0.2 <= metrics['stopword_ratio'] <= 0.4:
            score += 0.1
        else:
            score += 0.05
            
        metrics['quality_score'] = min(max(score, 0), 1)  # Normalize to 0-1 range
        return metrics

    def get_stopwords(self) -> List[str]:
        """Get a list of common stopwords"""
        return {
            'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', "you're", 
            "you've", "you'll", "you'd", 'your', 'yours', 'yourself', 'yourselves', 
            'he', 'him', 'his', 'himself', 'she', "she's", 'her', 'hers', 'herself', 
            'it', "it's", 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves', 
            'what', 'which', 'who', 'whom', 'this', 'that', "that'll", 'these', 'those', 
            'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 
            'having', 'do', 'does', 'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 
            'or', 'because', 'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with', 
            'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 
            'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 
            'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 
            'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 
            'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 
            'too', 'very', 's', 't', 'can', 'will', 'just', 'don', "don't", 'should', 
            "should've", 'now', 'd', 'll', 'm', 'o', 're', 've', 'y', 'ain', 'aren', 
            "aren't", 'couldn', "couldn't", 'didn', "didn't", 'doesn', "doesn't", 'hadn', 
            "hadn't", 'hasn', "hasn't", 'haven', "haven't", 'isn', "isn't", 'ma', 'mightn', 
            "mightn't", 'mustn', "mustn't", 'needn', "needn't", 'shan', "shan't", 'shouldn', 
            "shouldn't", 'wasn', "wasn't", 'weren', "weren't", 'won', "won't", 'wouldn', 
            "wouldn't"
        }