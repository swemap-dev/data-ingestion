import os
import hmac
import hashlib
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()


class WebhookVerifier:
    """Verify GitHub webhook signatures."""
    
    def __init__(self, webhook_secret: Optional[str] = None):
        """
        Initialize webhook verifier.
        
        Args:
            webhook_secret: GitHub webhook secret (defaults to GITHUB_WEBHOOK_SECRET env var)
        """
        self.webhook_secret = webhook_secret or os.getenv('GITHUB_WEBHOOK_SECRET')
        
        if not self.webhook_secret:
            raise ValueError("GitHub webhook secret is required. Set GITHUB_WEBHOOK_SECRET environment variable.")
    
    def verify_signature(self, payload_body: bytes, signature_header: Optional[str]) -> bool:
        """
        Verify the webhook signature using HMAC SHA-256.
        
        Args:
            payload_body: Raw request body as bytes
            signature_header: X-Hub-Signature-256 header value
        
        Returns:
            True if signature is valid, False otherwise
        """
        if not signature_header:
            return False
        
        # GitHub sends signature as "sha256=<hash>"
        if not signature_header.startswith('sha256='):
            return False
        
        expected_signature = signature_header[7:]  # Remove 'sha256=' prefix
        
        # Compute the signature
        computed_signature = hmac.new(
            self.webhook_secret.encode('utf-8'),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        
        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(expected_signature, computed_signature)
    
    def extract_repository_info(self, payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Extract repository owner and name from webhook payload.
        
        Args:
            payload: Webhook event payload
        
        Returns:
            Dictionary with 'owner' and 'repo' keys, or None if not found
        """
        repository = payload.get('repository')
        if not repository:
            return None
        
        owner = repository.get('owner', {}).get('login')
        repo = repository.get('name')
        
        if not owner or not repo:
            return None
        
        return {'owner': owner, 'repo': repo}

