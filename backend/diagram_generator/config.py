import spacy
import re
import os
import logging
from typing import List, Dict, Set, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== Enums and Dataclasses ==================

class DiagramType(Enum):
    USE_CASE = "usecase"
    SEQUENCE = "sequence"
    CLASS = "class"

@dataclass
class DiagramConfig:
    plantuml_server: str = "http://www.plantuml.com/plantuml/png/"
    output_format: str = "png"
    max_line_length: int = 1000

class DiagramGenerationError(Exception):
    pass

# ================== NLP Setup ==================

try:
    nlp = spacy.load("en_core_web_sm")
    logger.info("spaCy model loaded successfully")
except OSError:
    logger.error("spaCy model 'en_core_web_sm' not found. Install with: python -m spacy download en_core_web_sm")
    
    class DummyNLP:
        def __call__(self, text):
            return DummyDoc(text)
    
    class DummyDoc:
        def __init__(self, text):
            self.text = text
            self.ents = []
            self.tokens = [DummyToken(word) for word in text.split()]
        
        def __iter__(self):
            return iter(self.tokens)
    
    class DummyToken:
        def __init__(self, text):
            self.text = text
            self.pos_ = "NOUN" if text.isalpha() and len(text) > 2 else "PUNCT"
            self.dep_ = "nsubj"
            self.lemma_ = text.lower()
    
    nlp = DummyNLP()
    logger.warning("Using basic NLP - install spaCy model for better results")

# ================== Constants ==================

STOP_WORDS = {
    'the', 'a', 'an', 'to', 'is', 'are', 'of', 'and', 'with', 'for', 
    'in', 'on', 'at', 'by', 'from', 'this', 'that', 'will', 'be', 'have', 'has'
}

CLASS_BLACKLIST = {
    "system", "application", "service", "manager", "handler", "processor",
    "interface", "entity", "class", "method", "attribute", "diagram"
}

RELATIONSHIP_PATTERNS = {
    'extends': r'(.+?)\s+(?:extends|inherits from|extending into)\s+(.+)',
    'implements': r'(.+?)\s+implements\s+(.+)',
    'includes': r'(.+?)\s+includes\s+(.+)',
    'uses': r'(.+?)\s+(?:uses|has|contains|manages)\s+(.+)',
    'sends': r'(.+?)\s+(?:sends|calls|invokes)\s+(.+)',
    'wishes': r'(.+?)\s+(?:wishes to|wants to|needs to)\s+(.+)'
}

# ================== Utility Functions ==================

def clean_text(text: str) -> str:
    """Clean and normalize text by removing stop words and special characters."""
    if not text:
        return ""
    
    cleaned = re.sub(r'[^\w\s]', ' ', text).strip()
    words = []
    
    for word in cleaned.split():
        if (word.lower() not in STOP_WORDS and 
            len(word) > 1 and 
            word.lower() not in CLASS_BLACKLIST):
            words.append(word.capitalize())
    
    return " ".join(words) if words else text.strip()

def sanitize_id(text: str) -> str:
    """Sanitize text to create valid PlantUML identifiers."""
    if not text:
        return "undefined"
    
    sanitized = re.sub(r'[^\w]', '_', text)
    sanitized = re.sub(r'_+', '_', sanitized)
    sanitized = sanitized.strip('_')
    
    if sanitized and sanitized[0].isdigit():
        sanitized = 'id_' + sanitized
    
    if not sanitized:
        sanitized = 'element_' + str(abs(hash(text)))[:8]
    
    return sanitized