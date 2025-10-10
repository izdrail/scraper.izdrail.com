from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
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
    logger.error(
        "spaCy model 'en_core_web_md' not found. Please install it using: python -m spacy download en_core_web_md")
    raise

router = APIRouter(prefix="/api/v1", tags=["scrapper"])

# Configuration constants
SKRAPER_PATH = Path('/usr/local/bin/skraper')

# All supported networks from skraper CLI tool
ALLOWED_NETWORKS = {
    'facebook',
    'instagram',
    'twitter',
    'youtube',
    'tiktok',
    'telegram',
    'twitch',
    'reddit',
    '9gag',
    'pinterest',
    'flickr',
    'tumblr',
    'ifunny',
    'vk',
    'pikabu',
    'vimeo',
    'odnoklassniki',
    'coub'
}


class ScrapperAction(BaseModel):
    network: str
    query: str
    limit: int = 50  # Default limit as per skraper CLI
    media_only: bool = False  # Flag for media-only scraping (Note: disables JSON output)

    @field_validator('network')
    @classmethod
    def validate_network(cls, value: str) -> str:
        """Validate that the network is supported by skraper."""
        if value.lower() not in ALLOWED_NETWORKS:
            raise ValueError(
                f"Network must be one of: {', '.join(sorted(ALLOWED_NETWORKS))}"
            )
        return value.lower()

    @field_validator('limit')
    @classmethod
    def validate_limit(cls, value: int) -> int:
        """Validate that limit is a positive integer."""
        if value < 1:
            raise ValueError("Limit must be a positive integer")
        if value > 1000:
            raise ValueError("Limit cannot exceed 1000 posts")
        return value

    @field_validator('media_only')
    @classmethod
    def validate_media_only(cls, value: bool) -> bool:
        """Warn that media_only disables JSON output."""
        if value:
            logger.warning("media_only=True will download media files but won't produce JSON output for enrichment")
        return value


class EnrichedItem(BaseModel):
    original_item: Dict[str, Any]
    sentiment: float
    entities: List[Dict[str, Any]]
    keywords: List[str]


class EnrichedData(BaseModel):
    items: List[EnrichedItem]
    total_items: int
    average_sentiment: float


def enrich_data(data: Any) -> EnrichedData:
    """
    Enrich scraped data with NLP analysis for each item in the list.

    Args:
        data: Original scraped data (expected to be a list of dictionaries)

    Returns:
        EnrichedData with a list of enriched items and aggregate statistics
    """
    if not isinstance(data, list):
        logger.error(f"Expected a list for scraped data, got {type(data)}")
        raise ValueError("Scraped data must be a list of items")

    enriched_items = []
    sentiment_scores = []

    for item in data:
        if not isinstance(item, dict):
            logger.warning(f"Skipping invalid item: {item}")
            continue

        # Extract text content from various possible fields
        text_content = (
                item.get('text', '') or
                item.get('content', '') or
                item.get('description', '') or
                item.get('title', '') or
                ''
        )

        if not text_content:
            logger.warning(f"No text content found in item: {item.get('id', 'unknown')}")
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

            # Sentiment analysis using TextBlob
            sentiment = TextBlob(text_content).sentiment.polarity
            sentiment_scores.append(sentiment)

            # Named Entity Recognition
            entities = [
                {
                    "text": ent.text,
                    "label": ent.label_,
                    "start": ent.start_char,
                    "end": ent.end_char
                }
                for ent in doc.ents
            ]

            # Keyword extraction using noun chunks
            keywords = list(set(
                chunk.text.lower()
                for chunk in doc.noun_chunks
                if len(chunk.text) > 2
            ))

            enriched_items.append(EnrichedItem(
                original_item=item,
                sentiment=round(sentiment, 3),
                entities=entities,
                keywords=keywords[:10]  # Limit to top 10 keywords
            ))

        except Exception as e:
            logger.error(f"Error processing item {item.get('id', 'unknown')}: {str(e)}")
            enriched_items.append(EnrichedItem(
                original_item=item,
                sentiment=0.0,
                entities=[],
                keywords=[]
            ))

    if not enriched_items:
        logger.warning("No valid items were enriched")

    # Calculate average sentiment
    avg_sentiment = (
        round(sum(sentiment_scores) / len(sentiment_scores), 3)
        if sentiment_scores else 0.0
    )

    return EnrichedData(
        items=enriched_items,
        total_items=len(enriched_items),
        average_sentiment=avg_sentiment
    )


@router.post("/run/scrapper", response_model=dict)
async def run_scrapper(scrapper: ScrapperAction):
    """
    Execute scrapper CLI command and return enriched results with NLP analysis.

    Supports all 18 networks from skraper:
    - facebook, instagram, twitter, youtube, tiktok, telegram, twitch, reddit
    - 9gag, pinterest, flickr, tumblr, ifunny, vk, pikabu, vimeo, odnoklassniki, coub

    Args:
        scrapper: ScrapperAction model containing network, query, limit, and media_only flag

    Returns:
        Dictionary containing execution log, enriched scraped data, and metadata

    Raises:
        HTTPException: For various error conditions

    Note:
        - media_only=True downloads media files but does not produce JSON output
        - For structured data with NLP enrichment, use media_only=False (default)
    """
    # Verify skraper binary exists and is executable
    if not SKRAPER_PATH.exists():
        logger.error(f"Skraper binary not found at {SKRAPER_PATH}")
        raise HTTPException(
            status_code=500,
            detail=f"Skraper binary not found at {SKRAPER_PATH}"
        )

    if not SKRAPER_PATH.is_file() or not os.access(SKRAPER_PATH, os.X_OK):
        logger.error(f"Skraper binary at {SKRAPER_PATH} is not executable")
        raise HTTPException(
            status_code=500,
            detail="Skraper binary is not executable"
        )

    # Sanitize input (remove spaces but keep other characters for paths)
    safe_network = scrapper.network.replace(' ', '')
    safe_query = scrapper.query.strip()

    try:
        # Build command with all parameters
        cmd = [
            str(SKRAPER_PATH),
            safe_network,
            safe_query,
            '-n', str(scrapper.limit),
            '-t', 'json'
        ]

        # Add media-only flag if requested
        if scrapper.media_only:
            cmd.append('-m')

        logger.info(f"Executing command: {' '.join(cmd)}")

        # Execute command with timeout
        # Don't use check=True because stderr contains progress bars, not errors
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60  # Increased timeout for larger scrapes
        )

        # Check return code manually
        if result.returncode != 0:
            # Only treat as error if there's an actual error message (not just progress bars)
            error_lines = [
                line for line in result.stderr.splitlines()
                if line and not any(x in line for x in ['Fetching', '%', '│', '\u001b'])
            ]
            if error_lines:
                error_msg = '\n'.join(error_lines)
                logger.error(f"Scrapper command failed with return code {result.returncode}: {error_msg}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Skraper command execution failed: {error_msg}"
                )

        # Parse output for JSON file path from both stdout and stderr
        file_path = None
        combined_output = result.stdout + '\n' + result.stderr

        # Look for JSON file specifically (not media files)
        for line in combined_output.splitlines():
            if "has been written to" in line and ".json" in line.lower():
                file_path = line.split("has been written to ")[-1].strip()
                break

        # If media_only is True, we won't have a JSON file
        if scrapper.media_only:
            logger.info("Media-only mode: files downloaded but no JSON metadata available")
            raise HTTPException(
                status_code=400,
                detail="Media-only mode does not produce JSON output. Remove media_only flag or set it to false to get structured data."
            )

        if not file_path:
            logger.warning("Could not find JSON file path in output")
            logger.debug(f"Stdout: {result.stdout}")
            logger.debug(f"Stderr: {result.stderr}")
            raise HTTPException(
                status_code=500,
                detail="Could not find generated JSON file path in skraper output"
            )

        # Read and parse JSON file
        try:
            # Try different encodings
            json_data = None
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'iso-8859-1']

            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as json_file:
                        json_data = json.load(json_file)
                    logger.info(f"Successfully loaded data using {encoding} encoding")
                    break
                except (UnicodeDecodeError, json.JSONDecodeError) as decode_error:
                    logger.debug(f"Failed to read with {encoding}: {str(decode_error)}")
                    continue

            if json_data is None:
                # If all encodings fail, try reading as binary and detecting
                logger.info("Trying binary mode with error handling")
                with open(file_path, 'rb') as binary_file:
                    content = binary_file.read()
                    # Try to decode with error handling
                    text_content = content.decode('utf-8', errors='ignore')
                    json_data = json.loads(text_content)
                    logger.info("Successfully loaded data using binary mode with error handling")

            if json_data is None:
                raise ValueError("Failed to load JSON data with any encoding method")

            logger.info(
                f"Successfully loaded {len(json_data) if isinstance(json_data, list) else 1} items from {file_path}")

            # Enrich the data with NLP analysis
            try:
                enriched_data = enrich_data(json_data).dict()
                logger.info(f"Successfully enriched {enriched_data.get('total_items', 0)} items")
            except Exception as enrich_error:
                logger.error(f"Error during data enrichment: {str(enrich_error)}", exc_info=True)
                raise ValueError(f"Failed to enrich data: {str(enrich_error)}")

            # Clean up temporary file
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
            except OSError as e:
                logger.warning(f"Failed to remove temporary file {file_path}: {str(e)}")

            # Clean progress bars from stderr for cleaner logs
            clean_stderr = '\n'.join([
                line for line in result.stderr.splitlines()
                if line and not any(x in line for x in ['Fetching', '%', '│', '\u001b'])
            ])

            return {
                "success": True,
                "network": scrapper.network,
                "query": scrapper.query,
                "execution_log": result.stdout if result.stdout else clean_stderr,
                "scraped_data": enriched_data,
                "metadata": {
                    "requested_limit": scrapper.limit,
                    "actual_items": enriched_data['total_items'],
                    "media_only": scrapper.media_only
                }
            }

        except FileNotFoundError:
            logger.error(f"Generated file not found at {file_path}")
            raise HTTPException(
                status_code=500,
                detail=f"Generated file not found at {file_path}"
            )
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file {file_path}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse generated JSON file: {str(e)}"
            )

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or e.stdout or "Unknown error"
        logger.error(f"Scrapper command failed: {error_msg}")
        raise HTTPException(
            status_code=500,
            detail=f"Skraper command execution failed: {error_msg}"
        )
    except subprocess.TimeoutExpired:
        logger.error(f"Scrapper command timed out after 60 seconds")
        raise HTTPException(
            status_code=504,
            detail="Scrapper command timed out. Try reducing the limit or simplifying the query."
        )
    except ValueError as e:
        logger.error(f"Data validation error: {str(e)}")
        raise HTTPException(
            status_code=422,
            detail=f"Data processing error: {str(e)}"
        )
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        # Provide more detail about the error
        import traceback
        error_detail = f"Unexpected error occurred: {str(e) or type(e).__name__}"
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=error_detail
        )


@router.get("/scrapper/networks", response_model=dict)
async def get_supported_networks():
    """
    Get list of all supported networks/providers.

    Returns:
        Dictionary containing sorted list of supported networks with descriptions
    """
    network_info = {
        'facebook': 'Facebook posts and pages',
        'instagram': 'Instagram posts and profiles',
        'twitter': 'Twitter/X tweets and timelines',
        'youtube': 'YouTube videos and channels',
        'tiktok': 'TikTok videos and users',
        'telegram': 'Telegram channels and groups',
        'twitch': 'Twitch streams and clips',
        'reddit': 'Reddit posts and subreddits',
        '9gag': '9GAG posts and trends',
        'pinterest': 'Pinterest pins and boards',
        'flickr': 'Flickr photos and albums',
        'tumblr': 'Tumblr posts and blogs',
        'ifunny': 'IFunny memes and content',
        'vk': 'VK (VKontakte) posts and communities',
        'pikabu': 'Pikabu posts and stories',
        'vimeo': 'Vimeo videos and channels',
        'odnoklassniki': 'Odnoklassniki posts and groups',
        'coub': 'Coub loops and videos'
    }

    return {
        "total": len(ALLOWED_NETWORKS),
        "networks": sorted(ALLOWED_NETWORKS),
        "details": network_info
    }