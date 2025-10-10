from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
import subprocess
import json
import os
import logging
from pathlib import Path
import spacy
from textblob import TextBlob

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize spaCy
try:
    nlp = spacy.load("en_core_web_md")
except OSError:
    logger.error("spaCy model 'en_core_web_sm' not found. Please install it using: python -m spacy download en_core_web_sm")
    raise

router = APIRouter(prefix="/api/v1", tags=["scrapper"])

# Configuration constants
SKRAPER_PATH = Path('/usr/local/bin/skraper')
ALLOWED_NETWORKS = {'twitter', 'reddit', 'instagram', 'twitch', 'pinterest'}

class ScrapperAction(BaseModel):
    network: str
    query: str

    @classmethod
    def validate_network(cls, value: str) -> str:
        if value.lower() not in ALLOWED_NETWORKS:
            raise ValueError(f"Network must be one of: {', '.join(ALLOWED_NETWORKS)}")
        return value.lower()

class EnrichedItem(BaseModel):
    original_item: Dict[str, Any]
    sentiment: float
    entities: List[Dict[str, Any]]
    keywords: List[str]

class EnrichedData(BaseModel):
    items: List[EnrichedItem]

def enrich_data(data: Any) -> EnrichedData:
    """
    Enrich scraped data with NLP analysis for each item in the list.
    
    Args:
        data: Original scraped data (expected to be a list of dictionaries)
        
    Returns:
        EnrichedData with a list of enriched items
    """
    if not isinstance(data, list):
        logger.error(f"Expected a list for scraped data, got {type(data)}")
        raise ValueError("Scraped data must be a list of items")

    enriched_items = []
    
    for item in data:
        if not isinstance(item, dict):
            logger.warning(f"Skipping invalid item: {item}")
            continue
            
        # Extract text content (adjust based on your data structure)
        text_content = item.get('content', '') or item.get('text', '') or ''
        if not text_content:
            logger.warning(f"No text content found in item: {item}")
            enriched_items.append(EnrichedItem(
                original_item=item,
                sentiment=0.0,
                entities=[],
                keywords=[]
            ))
            continue
            
        try:
            # Process with spaCy
            doc = nlp(text_content)
            
            # Sentiment analysis
            sentiment = TextBlob(text_content).sentiment.polarity
            
            # Named Entity Recognition
            entities = [
                {"text": ent.text, "label": ent.label_, "start": ent.start_char, "end": ent.end_char}
                for ent in doc.ents
            ]
            
            # Keyword extraction
            keywords = list(set(chunk.text.lower() for chunk in doc.noun_chunks if len(chunk.text) > 2))
            
            enriched_items.append(EnrichedItem(
                original_item=item,
                sentiment=sentiment,
                entities=entities,
                keywords=keywords[:10]  # Limit to top 10 keywords
            ))
        except Exception as e:
            logger.error(f"Error processing item {item}: {str(e)}")
            enriched_items.append(EnrichedItem(
                original_item=item,
                sentiment=0.0,
                entities=[],
                keywords=[]
            ))
    
    if not enriched_items:
        logger.warning("No valid items were enriched")
    
    return EnrichedData(items=enriched_items)

@router.post("/run/scrapper", response_model=dict)
async def run_scrapper(scrapper: ScrapperAction):
    """
    Execute scrapper CLI command and return enriched results with NLP analysis.
    
    Args:
        scrapper: ScrapperAction model containing network and query
        
    Returns:
        Dictionary containing execution log and enriched scraped data
        
    Raises:
        HTTPException: For various error conditions
    """
    # Verify skraper binary
    if not SKRAPER_PATH.exists():
        logger.error(f"Skraper binary not found at {SKRAPER_PATH}")
        raise HTTPException(status_code=500, detail="Skraper binary not found")
    
    if not SKRAPER_PATH.is_file() or not os.access(SKRAPER_PATH, os.X_OK):
        logger.error(f"Skraper binary at {SKRAPER_PATH} is not executable")
        raise HTTPException(status_code=500, detail="Skraper binary not executable")

    # Sanitize input
    safe_network = scrapper.network.replace(' ', '')
    safe_query = scrapper.query.replace(' ', '')

    try:
        # Execute command
        cmd = [str(SKRAPER_PATH), safe_network, safe_query, '-t', 'json']
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )

        # Parse output for file path
        file_path = None
        for line in result.stdout.splitlines():
            if "has been written to" in line:
                file_path = line.split("has been written to ")[-1].strip()
                break

        if not file_path:
            logger.warning("Could not find generated file path in output")
            raise HTTPException(status_code=500, detail="Could not find generated file path")

        # Read and parse JSON file
        try:
            with open(file_path, 'r') as json_file:
                json_data = json.load(json_file)
            
            # Enrich the data
            enriched_data = enrich_data(json_data).dict()
            
            # Clean up temporary file
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
            except OSError as e:
                logger.warning(f"Failed to remove temporary file {file_path}: {str(e)}")

            return {
                "execution_log": result.stdout,
                "scraped_data": enriched_data
            }

        except FileNotFoundError:
            logger.error(f"Generated file not found at {file_path}")
            raise HTTPException(status_code=500, detail=f"Generated file not found at {file_path}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file {file_path}: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to parse generated JSON file")

    except subprocess.CalledProcessError as e:
        logger.error(f"Scrapper command failed: {e.stderr}")
        raise HTTPException(status_code=500, detail=f"Command execution failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("Scrapper command timed out")
        raise HTTPException(status_code=504, detail="Scrapper command timed out")