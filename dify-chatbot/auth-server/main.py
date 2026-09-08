"""
SAML Authentication Server for HelpDesk Chatbot
Handles Azure AD SAML SSO
"""
import os
import json
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import jwt

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BASE_URL = os.environ.get("BASE_URL", "https://helpdesk.gokarla.net")
JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Azure AD SAML Configuration
TENANT_ID = "0e7486f4-86f7-4695-9c58-5a1f261871c9"
AZURE_SSO_URL = f"https://login.microsoftonline.com/{TENANT_ID}/saml2"
AZURE_ENTITY_ID = f"https://sts.windows.net/{TENANT_ID}/"

# Service Provider Configuration
SP_ENTITY_ID = BASE_URL
SP_ACS_URL = f"{BASE_URL}/api/auth/saml/acs"

app = FastAPI(title="HelpDesk Auth Server", version="1.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[BASE_URL, "http://localhost:4000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (use Redis in production)
sessions = {}

class UserInfo(BaseModel):
    email: str
    name: str
    given_name: Optional[str] = None
    surname: Optional[str] = None
    object_id: Optional[str] = None


def create_jwt_token(user_info: dict) -> str:
    """Create JWT token for authenticated user"""
    payload = {
        **user_info,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token: str) -> Optional[dict]:
    """Verify JWT token and return user info"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        return None


def create_saml_request() -> str:
    """Create SAML AuthnRequest"""
    import base64
    import zlib
    from datetime import datetime
    import uuid
    
    request_id = f"_{''.join(secrets.token_hex(16))}"
    issue_instant = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    saml_request = f'''<?xml version="1.0" encoding="UTF-8"?>
<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
    ID="{request_id}"
    Version="2.0"
    IssueInstant="{issue_instant}"
    Destination="{AZURE_SSO_URL}"
    AssertionConsumerServiceURL="{SP_ACS_URL}"
    ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">
    <saml:Issuer>{SP_ENTITY_ID}</saml:Issuer>
    <samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" AllowCreate="true"/>
</samlp:AuthnRequest>'''
    
    # Compress and encode
    compressed = zlib.compress(saml_request.encode('utf-8'))[2:-4]  # Remove zlib header/trailer
    encoded = base64.b64encode(compressed).decode('utf-8')
    
    return encoded


def parse_saml_response(saml_response: str) -> Optional[dict]:
    """Parse SAML Response and extract user attributes"""
    import base64
    import xml.etree.ElementTree as ET
    
    try:
        # Decode the SAML response
        decoded = base64.b64decode(saml_response)
        
        # Parse XML
        root = ET.fromstring(decoded)
        
        # Define namespaces
        namespaces = {
            'samlp': 'urn:oasis:names:tc:SAML:2.0:protocol',
            'saml': 'urn:oasis:names:tc:SAML:2.0:assertion',
        }
        
        # Check status
        status = root.find('.//samlp:StatusCode', namespaces)
        if status is not None:
            status_value = status.get('Value', '')
            if 'Success' not in status_value:
                logger.error(f"SAML Response status: {status_value}")
                return None
        
        # Extract user attributes
        user_info = {}
        
        # Get NameID (usually email)
        name_id = root.find('.//saml:NameID', namespaces)
        if name_id is not None and name_id.text:
            user_info['email'] = name_id.text
        
        # Get attributes
        attributes = root.findall('.//saml:Attribute', namespaces)
        for attr in attributes:
            attr_name = attr.get('Name', '')
            attr_value = attr.find('saml:AttributeValue', namespaces)
            value = attr_value.text if attr_value is not None and attr_value.text else ''
            
            # Map common attribute names
            if 'givenname' in attr_name.lower():
                user_info['given_name'] = value
            elif 'surname' in attr_name.lower():
                user_info['surname'] = value
            elif 'emailaddress' in attr_name.lower():
                user_info['email'] = value
            elif 'name' in attr_name.lower() and 'given' not in attr_name.lower():
                user_info['name'] = value
            elif 'displayname' in attr_name.lower():
                user_info['display_name'] = value
            elif 'objectidentifier' in attr_name.lower():
                user_info['object_id'] = value
        
        # Construct full name if not present
        if 'name' not in user_info:
            parts = []
            if user_info.get('given_name'):
                parts.append(user_info['given_name'])
            if user_info.get('surname'):
                parts.append(user_info['surname'])
            if parts:
                user_info['name'] = ' '.join(parts)
            elif user_info.get('email'):
                user_info['name'] = user_info['email'].split('@')[0]
        
        logger.info(f"Parsed user info: {user_info}")
        return user_info if user_info.get('email') else None
        
    except Exception as e:
        logger.error(f"Error parsing SAML response: {e}")
        return None


@app.get("/api/auth/saml/login")
async def saml_login(request: Request):
    """Initiate SAML login - redirect to Azure AD"""
    saml_request = create_saml_request()
    
    # Build redirect URL
    params = urlencode({
        'SAMLRequest': saml_request,
        'RelayState': BASE_URL,
    })
    
    redirect_url = f"{AZURE_SSO_URL}?{params}"
    logger.info(f"Redirecting to Azure AD: {redirect_url[:100]}...")
    
    return RedirectResponse(url=redirect_url, status_code=302)


@app.post("/api/auth/saml/acs")
async def saml_acs(request: Request):
    """SAML Assertion Consumer Service - handle Azure AD response"""
    try:
        form_data = await request.form()
        saml_response = form_data.get('SAMLResponse')
        relay_state = form_data.get('RelayState', BASE_URL)
        
        if not saml_response:
            logger.error("No SAMLResponse in request")
            raise HTTPException(status_code=400, detail="Missing SAMLResponse")
        
        # Parse the SAML response
        user_info = parse_saml_response(saml_response)
        
        if not user_info:
            logger.error("Failed to parse SAML response")
            raise HTTPException(status_code=401, detail="Invalid SAML response")
        
        # Create JWT token
        token = create_jwt_token(user_info)
        
        # Redirect to frontend with token
        redirect_url = f"{BASE_URL}/?token={token}"
        
        logger.info(f"User authenticated: {user_info.get('email')}")
        return RedirectResponse(url=redirect_url, status_code=302)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in SAML ACS: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/auth/saml/logout")
async def saml_logout(request: Request):
    """Handle logout - clear session and redirect"""
    # In a full implementation, would send SAML LogoutRequest to IdP
    response = RedirectResponse(url=BASE_URL, status_code=302)
    response.delete_cookie("auth_token")
    return response


@app.get("/api/auth/me")
async def get_current_user(request: Request):
    """Get current authenticated user info"""
    # Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    token = None
    
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        # Check cookie
        token = request.cookies.get("auth_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_info = verify_jwt_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return {
        "authenticated": True,
        "user": {
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "given_name": user_info.get("given_name"),
            "surname": user_info.get("surname"),
        }
    }


@app.get("/api/auth/verify")
async def verify_token(token: str):
    """Verify a JWT token"""
    user_info = verify_jwt_token(token)
    if not user_info:
        return {"valid": False}
    
    return {
        "valid": True,
        "user": {
            "email": user_info.get("email"),
            "name": user_info.get("name"),
        }
    }


@app.get("/api/auth/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "auth-server"}


@app.get("/api/auth/config")
async def get_config():
    """Get SAML configuration for debugging"""
    return {
        "sp_entity_id": SP_ENTITY_ID,
        "sp_acs_url": SP_ACS_URL,
        "idp_sso_url": AZURE_SSO_URL,
        "idp_entity_id": AZURE_ENTITY_ID,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

