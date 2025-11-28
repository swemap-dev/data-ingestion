import os
import time
import jwt
import requests
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class GitHubApp:
    """GitHub App authentication handler for JWT token generation and installation token exchange."""
    
    def __init__(self, app_id: Optional[str] = None, private_key: Optional[str] = None):
        """
        Initialize GitHub App.
        
        Args:
            app_id: GitHub App ID (defaults to GITHUB_APP_ID env var)
            private_key: GitHub App private key (defaults to GITHUB_APP_PRIVATE_KEY env var)
        """
        self.app_id = app_id or os.getenv('GITHUB_APP_ID')
        private_key_raw = private_key or os.getenv('GITHUB_APP_PRIVATE_KEY')
        
        if not self.app_id:
            raise ValueError("GitHub App ID is required. Set GITHUB_APP_ID environment variable.")
        if not private_key_raw:
            raise ValueError("GitHub App private key is required. Set GITHUB_APP_PRIVATE_KEY environment variable.")
        
        # Handle private key - could be a file path or the key itself
        if os.path.isfile(private_key_raw):
            # If it's a file path, read the file
            try:
                with open(private_key_raw, 'r') as f:
                    self.private_key = f.read()
            except Exception as e:
                raise ValueError(f"Failed to read private key from file {private_key_raw}: {e}")
        else:
            # It's the key content itself
            self.private_key = private_key_raw
        
        # Clean up the private key format
        # Remove surrounding quotes if present
        self.private_key = self.private_key.strip()
        if (self.private_key.startswith('"') and self.private_key.endswith('"')) or \
           (self.private_key.startswith("'") and self.private_key.endswith("'")):
            self.private_key = self.private_key[1:-1]
        
        # Replace escaped newlines with actual newlines
        self.private_key = self.private_key.replace('\\n', '\n')
        
        self.base_url = 'https://api.github.com'
    
    def generate_jwt_token(self) -> str:
        """
        Generate a JWT token for GitHub App authentication.
        
        Returns:
            JWT token string
        
        Raises:
            ValueError: If the private key is invalid or JWT encoding fails
        """
        now = int(time.time())
        payload = {
            'iat': now - 60,  # Issued at time (60 seconds in the past to allow for clock skew)
            'exp': now + (10 * 60),  # Expires in 10 minutes
            'iss': self.app_id  # Issuer (GitHub App ID)
        }
        
        try:
            token = jwt.encode(payload, self.private_key, algorithm='RS256')
            return token
        except Exception as e:
            error_msg = str(e)
            if 'no start line' in error_msg.lower() or 'deserialize' in error_msg.lower():
                raise ValueError(
                    f"Invalid private key format. The key may be missing proper newlines or headers. "
                    f"Make sure your GITHUB_APP_PRIVATE_KEY includes '\\n' for newlines, or use a file path. "
                    f"Original error: {error_msg}"
                )
            raise ValueError(f"Failed to generate JWT token: {error_msg}")
    
    def get_installation_id(self, organization: Optional[str] = None) -> Optional[int]:
        """
        Get the installation ID for the app in the specified organization.
        
        Args:
            organization: Organization name (optional, will try to find any installation)
        
        Returns:
            Installation ID or None if not found
        """
        jwt_token = self.generate_jwt_token()
        headers = {
            'Authorization': f'Bearer {jwt_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        url = f'{self.base_url}/app/installations'
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        installations = response.json()
        
        if organization:
            for installation in installations:
                if installation.get('account', {}).get('login') == organization:
                    return installation['id']
        elif installations:
            # Return first installation if no org specified
            return installations[0]['id']
        
        return None
    
    def get_installation_token(self, installation_id: Optional[int] = None) -> str:
        """
        Exchange JWT token for an installation access token.
        
        Args:
            installation_id: Installation ID (optional, will try to find one)
        
        Returns:
            Installation access token
        """
        if not installation_id:
            installation_id = self.get_installation_id()
            if not installation_id:
                raise ValueError("No installation found. Please install the app in your organization.")
        
        jwt_token = self.generate_jwt_token()
        headers = {
            'Authorization': f'Bearer {jwt_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        url = f'{self.base_url}/app/installations/{installation_id}/access_tokens'
        response = requests.post(url, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        return data['token']

