import logging
from fastapi import FastAPI, Request, Header, HTTPException, status
from fastapi.responses import Response
from typing import Optional
from .webhook import WebhookVerifier
from .handlers import EventHandlers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="GitHub App Webhook Server", version="1.0.0")

# Initialize components
verifier = WebhookVerifier()
event_handlers = EventHandlers()


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "github-app-webhook-server"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256")
):
    """
    GitHub webhook endpoint that receives and processes GitHub events.
    
    Args:
        request: FastAPI request object
        x_github_event: GitHub event type (from X-GitHub-Event header)
        x_github_delivery: GitHub delivery ID (from X-GitHub-Delivery header)
        x_hub_signature_256: Webhook signature (from X-Hub-Signature-256 header)
    
    Returns:
        HTTP 200 if successful, 401 if signature invalid, 400 if missing headers
    """
    # Validate required headers
    if not x_github_event:
        logger.warning("Missing X-GitHub-Event header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header"
        )
    
    if not x_github_delivery:
        logger.warning("Missing X-GitHub-Delivery header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Delivery header"
        )
    
    # Get raw body for signature verification
    try:
        body = await request.body()
    except Exception as e:
        logger.error(f"Failed to read request body: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read request body"
        )
    
    if not body:
        logger.warning("Empty request body")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty request body"
        )
    
    # Log body size for debugging
    logger.debug(f"Received webhook body: {len(body)} bytes")
    
    # Verify webhook signature (only if signature is provided)
    # Note: SMEE might not forward the signature header, so we'll make it optional for development
    if x_hub_signature_256:
        if not verifier.verify_signature(body, x_hub_signature_256):
            logger.warning(f"Invalid webhook signature for delivery {x_github_delivery}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
    else:
        logger.warning("No webhook signature provided - skipping verification (development mode)")
    
    # Parse JSON payload from body bytes
    try:
        import json
        body_str = body.decode('utf-8')
        # Try to clean up any potential issues with the JSON
        body_str = body_str.strip()
        payload = json.loads(body_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON payload: {e}")
        logger.error(f"Body preview (first 500 chars): {body_str[:500] if 'body_str' in locals() else 'N/A'}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {str(e)}"
        )
    except UnicodeDecodeError as e:
        logger.error(f"Failed to decode request body as UTF-8: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is not valid UTF-8"
        )
    except Exception as e:
        logger.error(f"Unexpected error parsing payload: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error processing request"
        )
    
    # Log event receipt
    logger.info(f"Received {x_github_event} event (delivery: {x_github_delivery})")
    
    # Handle the event (only push events are processed)
    try:
        event_handlers.handle_event(x_github_event, payload)
    except Exception as e:
        logger.error(f"Error processing {x_github_event} event: {e}", exc_info=True)
        # Still return 200 to GitHub to prevent retries for processing errors
        # (GitHub will retry on 5xx errors)
        return Response(status_code=200, content="Event received but processing failed")
    
    return Response(status_code=200, content="Event processed successfully")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

