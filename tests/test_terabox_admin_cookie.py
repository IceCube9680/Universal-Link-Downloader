import asyncio
import io
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pyrogram.types import Message, User as PyrogramUser

from app.bot.filters.admin import admin_filter, is_admin_user
from app.bot.handlers.admin import (
    register_admin_handlers,
    is_pending_cookie_admin,
    clear_pending_cookie_admin,
    _pending_cookie_admins
)
from app.core.config import settings
from app.core.crypto import encrypt_secret, decrypt_secret, derive_fernet_key
from app.core.logging import SecretMaskingFilter, setup_logging
from app.database.database import Database
from app.database.repository import SettingsRepository
from app.downloaders.terabox.credentials import (
    TeraBoxCredentialProvider,
    terabox_credentials,
    validate_and_normalize_cookie,
    SETTING_KEY_TERABOX_COOKIE
)
from app.downloaders.terabox.client import TeraBoxClient, format_terabox_cookie
from app.downloaders.terabox.resolver import TeraBoxResolver


@pytest.fixture(autouse=True)
def clean_cookie_state():
    _pending_cookie_admins.clear()
    settings.ADMIN_IDS = [1001, 1002]
    settings.TERABOX_COOKIE = ""
    yield
    _pending_cookie_admins.clear()
    settings.TERABOX_COOKIE = ""


# --- 1. Encryption at Rest & Key Derivation Tests ---

def test_crypto_encryption_and_decryption():
    test_secret = "ndus=fake_ndus_token_12345; lang=en"
    encrypted = encrypt_secret(test_secret)
    assert encrypted != test_secret
    assert "fake_ndus_token" not in encrypted

    decrypted = decrypt_secret(encrypted)
    assert decrypted == test_secret


def test_crypto_decryption_failure_safe_handling():
    corrupted = "gAAAAABlInvalidFernetCiphertextHeader=="
    decrypted = decrypt_secret(corrupted)
    assert decrypted is None  # Must return None without throwing unhandled crash


def test_crypto_key_derivation_fallback():
    key1 = derive_fernet_key("explicit_secret_key")
    assert len(key1) == 44  # Valid urlsafe base64 Fernet key

    key2 = derive_fernet_key("")
    assert len(key2) == 44


# --- 2. Cookie Validation & Normalization Tests ---

def test_cookie_validation_empty_and_whitespace():
    assert validate_and_normalize_cookie("")[0] is False
    assert validate_and_normalize_cookie("   ")[0] is False
    assert validate_and_normalize_cookie(None)[0] is False


def test_cookie_validation_excessive_length():
    huge_input = "a" * 5000
    valid, _, err = validate_and_normalize_cookie(huge_input)
    assert valid is False
    assert "exceeds maximum allowed length" in err


def test_cookie_validation_control_characters_rejection():
    dirty = "ndus=token\x00corrupt; lang=en"
    valid, _, err = validate_and_normalize_cookie(dirty)
    assert valid is False
    assert "control characters" in err


def test_cookie_validation_command_or_url_rejection():
    assert validate_and_normalize_cookie("/setteraboxcookie token")[0] is False
    assert validate_and_normalize_cookie("https://terabox.com/s/123")[0] is False


def test_cookie_normalization_raw_token():
    valid, norm, _ = validate_and_normalize_cookie("raw_token_xyz123")
    assert valid is True
    assert "ndus=raw_token_xyz123" in norm
    assert "lang=en" in norm


def test_cookie_normalization_full_browser_string():
    raw = "ndus=my_ndus_val; TSID=my_tsid; csrfToken=my_csrf"
    valid, norm, _ = validate_and_normalize_cookie(raw)
    assert valid is True
    assert "ndus=my_ndus_val" in norm
    assert "TSID=my_tsid" in norm
    assert "csrfToken=my_csrf" in norm
    assert "lang=en" in norm


# --- 3. Database Credential Provider & Precedence Tests ---

@pytest.mark.asyncio
async def test_credential_provider_database_storage_and_refresh(temp_db):
    provider = TeraBoxCredentialProvider()
    await provider.initialize(temp_db)

    assert provider.get_terabox_cookie() is None
    assert provider.get_cookie_source() == "none"

    # Set new cookie
    success, msg = await provider.set_cookie("ndus=test_db_cookie_val_123")
    assert success is True
    assert provider.get_cookie_source() == "database"
    assert "ndus=test_db_cookie_val_123" in provider.get_terabox_cookie()

    # Verify encrypted in raw database
    repo = SettingsRepository(temp_db)
    raw_in_db = await repo.get_setting(SETTING_KEY_TERABOX_COOKIE)
    assert raw_in_db is not None
    assert "test_db_cookie_val_123" not in raw_in_db  # Plaintext never stored in DB!

    # Clear cookie
    await provider.clear_cookie()
    assert provider.get_terabox_cookie() is None
    assert provider.get_cookie_source() == "none"
    assert await repo.get_setting(SETTING_KEY_TERABOX_COOKIE) is None


@pytest.mark.asyncio
async def test_credential_provider_precedence(temp_db):
    provider = TeraBoxCredentialProvider()
    await provider.initialize(temp_db)

    # 1. When DB cookie and Env cookie both exist, DB cookie takes precedence
    settings.TERABOX_COOKIE = "ndus=env_cookie_fallback"
    await provider.set_cookie("ndus=db_cookie_primary")
    assert "db_cookie_primary" in provider.get_terabox_cookie()
    assert provider.get_cookie_source() == "database"

    # 2. When DB cookie is cleared, falls back to Env cookie
    await provider.clear_cookie()
    assert "env_cookie_fallback" in provider.get_terabox_cookie()
    assert provider.get_cookie_source() == "environment"

    # 3. When Env cookie is also empty, falls back to cookie-free mode (None)
    settings.TERABOX_COOKIE = ""
    await provider.refresh()
    assert provider.get_terabox_cookie() is None
    assert provider.get_cookie_source() == "none"


@pytest.mark.asyncio
async def test_credential_provider_decryption_failure_fallback(temp_db):
    provider = TeraBoxCredentialProvider()
    await provider.initialize(temp_db)

    # Corrupt stored value in database
    repo = SettingsRepository(temp_db)
    await repo.set_setting(SETTING_KEY_TERABOX_COOKIE, "gAAAAABlInvalidCorruptData==")

    # Set env fallback
    settings.TERABOX_COOKIE = "ndus=env_fallback_safe"

    # Refresh provider
    await provider.refresh()
    # Should safely fall back to env cookie without crashing
    assert "env_fallback_safe" in provider.get_terabox_cookie()
    assert provider.get_cookie_source() == "environment"


@pytest.mark.asyncio
async def test_credential_provider_atomic_update_preserves_on_db_error(temp_db):
    provider = TeraBoxCredentialProvider()
    await provider.initialize(temp_db)
    await provider.set_cookie("ndus=initial_safe_cookie")

    # Mock DB write failure
    with patch.object(provider._settings_repo, "set_setting", AsyncMock(return_value=False)):
        success, _ = await provider.set_cookie("ndus=new_failing_cookie")
        assert success is False
        # Old runtime credential must be preserved
        assert "initial_safe_cookie" in provider.get_terabox_cookie()


# --- 4. Admin Command Handlers Tests ---

def setup_mock_handlers(db: Database):
    registered_handlers = {}
    registered_callbacks = []

    def mock_on_message(flt, group=0):
        def decorator(func):
            registered_handlers[func.__name__] = func
            return func
        return decorator

    def mock_on_callback(flt):
        def decorator(func):
            registered_callbacks.append(func)
            return func
        return decorator

    mock_app = MagicMock()
    mock_app.on_message = mock_on_message
    mock_app.on_callback_query = mock_on_callback

    register_admin_handlers(mock_app, db)
    return registered_handlers


@pytest.mark.asyncio
async def test_admin_setteraboxcookie_direct_command(temp_db):
    await terabox_credentials.initialize(temp_db)
    handlers = setup_mock_handlers(temp_db)

    set_func = handlers["admin_set_terabox_cookie_handler"]

    mock_client = MagicMock()
    mock_msg = MagicMock(spec=Message)
    mock_msg.from_user = MagicMock(spec=PyrogramUser, id=1001)
    mock_msg.text = "/setteraboxcookie ndus=valid_admin_token_123"
    mock_msg.reply_text = AsyncMock()
    mock_msg.delete = AsyncMock()

    with patch.object(terabox_credentials, "verify_session", AsyncMock(return_value=True)):
        await set_func(mock_client, mock_msg)

    # Message deletion must be attempted for privacy
    assert mock_msg.delete.called
    assert mock_msg.reply_text.called
    reply_text = mock_msg.reply_text.call_args[0][0]
    assert "TeraBox cookie updated and verified" in reply_text
    # Secret must never be in response text
    assert "valid_admin_token_123" not in reply_text
    assert "ndus=" not in reply_text

    # Runtime must immediately reflect update
    assert "valid_admin_token_123" in terabox_credentials.get_terabox_cookie()


@pytest.mark.asyncio
async def test_admin_setteraboxcookie_interactive_workflow(temp_db):
    await terabox_credentials.initialize(temp_db)
    handlers = setup_mock_handlers(temp_db)

    set_func = handlers["admin_set_terabox_cookie_handler"]
    resp_func = handlers["admin_pending_cookie_response_handler"]

    mock_client = MagicMock()
    mock_msg1 = MagicMock(spec=Message)
    mock_msg1.from_user = MagicMock(spec=PyrogramUser, id=1001)
    mock_msg1.text = "/setteraboxcookie"
    mock_msg1.reply_text = AsyncMock()

    # 1. Admin sends /setteraboxcookie without arg
    await set_func(mock_client, mock_msg1)
    assert mock_msg1.reply_text.called
    assert "Send the new TeraBox cookie" in mock_msg1.reply_text.call_args[0][0]
    assert is_pending_cookie_admin(1001) is True

    # 2. Admin sends cookie message
    mock_msg2 = MagicMock(spec=Message)
    mock_msg2.from_user = MagicMock(spec=PyrogramUser, id=1001)
    mock_msg2.text = "ndus=interactive_session_token_456"
    mock_msg2.reply_text = AsyncMock()
    mock_msg2.delete = AsyncMock()
    mock_msg2.stop_propagation = MagicMock()

    with patch.object(terabox_credentials, "verify_session", AsyncMock(return_value=None)):
        await resp_func(mock_client, mock_msg2)

    assert mock_msg2.delete.called
    assert mock_msg2.reply_text.called
    assert "TeraBox cookie updated successfully" in mock_msg2.reply_text.call_args[0][0]
    assert "interactive_session_token" not in mock_msg2.reply_text.call_args[0][0]
    assert is_pending_cookie_admin(1001) is False
    assert "interactive_session_token_456" in terabox_credentials.get_terabox_cookie()


@pytest.mark.asyncio
async def test_admin_clearteraboxcookie_command(temp_db):
    await terabox_credentials.initialize(temp_db)
    await terabox_credentials.set_cookie("ndus=to_be_cleared_token")
    handlers = setup_mock_handlers(temp_db)

    clear_func = handlers["admin_clear_terabox_cookie_handler"]

    mock_client = MagicMock()
    mock_msg = MagicMock(spec=Message)
    mock_msg.from_user = MagicMock(spec=PyrogramUser, id=1001)
    mock_msg.text = "/clearteraboxcookie"
    mock_msg.reply_text = AsyncMock()

    await clear_func(mock_client, mock_msg)
    assert mock_msg.reply_text.called
    reply_text = mock_msg.reply_text.call_args[0][0]
    assert "TeraBox database cookie cleared" in reply_text
    assert "to_be_cleared" not in reply_text
    assert terabox_credentials.get_terabox_cookie() is None


@pytest.mark.asyncio
async def test_admin_teraboxcookiestatus_command(temp_db):
    await terabox_credentials.initialize(temp_db)
    handlers = setup_mock_handlers(temp_db)

    status_func = handlers["admin_terabox_cookie_status_handler"]

    mock_client = MagicMock()
    mock_msg = MagicMock(spec=Message)
    mock_msg.from_user = MagicMock(spec=PyrogramUser, id=1001)
    mock_msg.text = "/teraboxcookiestatus"
    mock_msg.reply_text = AsyncMock()

    # 1. Unconfigured state
    await status_func(mock_client, mock_msg)
    text1 = mock_msg.reply_text.call_args[0][0]
    assert "Database:** `not configured`" in text1
    assert "Runtime:** `cookie-free mode`" in text1

    # 2. Configured state
    await terabox_credentials.set_cookie("ndus=secret_session_token_999; TSID=secret_tsid_111")
    await status_func(mock_client, mock_msg)
    text2 = mock_msg.reply_text.call_args[0][0]
    assert "Database:** `configured`" in text2
    assert "Runtime:** `loaded (database)`" in text2

    # Verify no secret leakage
    assert "secret_session_token" not in text2
    assert "secret_tsid" not in text2
    assert "ndus=" not in text2
    assert "TSID=" not in text2


@pytest.mark.asyncio
async def test_unauthorized_user_rejected(temp_db):
    await terabox_credentials.initialize(temp_db)
    handlers = setup_mock_handlers(temp_db)

    unauth_func = handlers["admin_unauthorized_terabox_cookie_handler"]

    mock_client = MagicMock()
    mock_msg = MagicMock(spec=Message)
    mock_msg.from_user = MagicMock(spec=PyrogramUser, id=9999)  # Non-admin
    mock_msg.text = "/setteraboxcookie malicious_attempt_token"
    mock_msg.reply_text = AsyncMock()
    mock_msg.delete = AsyncMock()

    await unauth_func(mock_client, mock_msg)
    assert mock_msg.delete.called
    assert mock_msg.reply_text.called
    assert "not authorized" in mock_msg.reply_text.call_args[0][0]
    # Verify DB was NOT touched by unauthorized user
    assert terabox_credentials.get_terabox_cookie() is None


# --- 5. Secret Redaction & Logging Tests ---

def test_secret_redaction_in_logging():
    filter_ = SecretMaskingFilter()
    sensitive_message = (
        "Logs containing ndus=TEST_SECRET_COOKIE_VALUE; "
        "TSID=TSID_SECRET_VAL; csrfToken=CSRF_SECRET_VAL; "
        "terabox_cookie='TEST_SECRET_COOKIE_VALUE'; "
        "TERABOX_COOKIE=TEST_SECRET_COOKIE_VALUE"
    )
    masked = filter_.mask_secrets(sensitive_message)
    assert "TEST_SECRET_COOKIE_VALUE" not in masked
    assert "TSID_SECRET_VAL" not in masked
    assert "CSRF_SECRET_VAL" not in masked
    assert "[REDACTED]" in masked


# --- 6. TeraBox Client & Resolver Dynamic Refresh Tests ---

@pytest.mark.asyncio
async def test_terabox_client_and_resolver_dynamic_cookie_integration(temp_db):
    await terabox_credentials.initialize(temp_db)
    client = TeraBoxClient()
    resolver = TeraBoxResolver(client=client)

    # 1. Initial cookie-free state
    assert client.has_configured_cookie is False
    headers = client.get_base_headers("www.terabox.app", include_cookie=True)
    assert "Cookie" not in headers

    # 2. Admin updates cookie at runtime
    await terabox_credentials.set_cookie("ndus=newly_updated_runtime_cookie")
    assert client.has_configured_cookie is True
    assert client.is_cookie_usable is True

    headers = client.get_base_headers("www.terabox.app", include_cookie=True)
    assert "Cookie" in headers
    assert "ndus=newly_updated_runtime_cookie" in headers["Cookie"]

    # 3. Admin clears cookie
    await terabox_credentials.clear_cookie()
    assert client.has_configured_cookie is False
    headers_after_clear = client.get_base_headers("www.terabox.app", include_cookie=True)
    assert "Cookie" not in headers_after_clear


@pytest.mark.asyncio
async def test_terabox_resolver_authenticated_fallback_uses_dynamic_cookie(temp_db):
    await terabox_credentials.initialize(temp_db)
    await terabox_credentials.set_cookie("ndus=resolver_test_cookie_999")

    client = TeraBoxClient()
    resolver = TeraBoxResolver(client=client)

    api_resp = {
        "errno": 0,
        "list": [
            {
                "server_filename": "auth_protected_file.zip",
                "size": 204800,
                "dlink": "https://d-auth.terabox.com/file.zip"
            }
        ]
    }

    # Simulate: Cookie-free attempt fails (raises or returns empty), authenticated attempt succeeds
    call_count = 0
    def mock_pipeline(link_info, session, use_cookie):
        nonlocal call_count
        call_count += 1
        from app.downloaders.terabox.models import TeraBoxResolutionResult, TeraBoxFile, TeraBoxErrorType
        if not use_cookie:
            # Cookie-free fails
            return TeraBoxResolutionResult(success=False, error_type=TeraBoxErrorType.AUTH_EXPIRED, link_info=link_info)
        else:
            # Authenticated fallback succeeds
            f = TeraBoxFile(
                filename="auth_protected_file.zip",
                size=204800,
                direct_url="https://d-auth.terabox.com/file.zip"
            )
            return TeraBoxResolutionResult(success=True, file=f, link_info=link_info)

    with patch.object(resolver, "_execute_resolution_pipeline", side_effect=mock_pipeline):
        with patch("app.downloaders.terabox.resolver.validate_url_security", AsyncMock()):
            mock_session = MagicMock()
            resolved = await resolver.resolve("https://terabox.com/s/1auth999", session=mock_session)
            assert resolved.direct_url == "https://d-auth.terabox.com/file.zip"
            assert resolved.headers is not None
            assert "Cookie" in resolved.headers
            assert "ndus=resolver_test_cookie_999" in resolved.headers["Cookie"]
            assert call_count == 2  # 1st cookie-free, 2nd authenticated fallback


@pytest.mark.asyncio
async def test_concurrent_admin_cookie_updates(temp_db):
    await terabox_credentials.initialize(temp_db)

    # Run 5 concurrent admin cookie updates
    results = await asyncio.gather(
        terabox_credentials.set_cookie("ndus=cookie_concurrent_1"),
        terabox_credentials.set_cookie("ndus=cookie_concurrent_2"),
        terabox_credentials.set_cookie("ndus=cookie_concurrent_3"),
        terabox_credentials.set_cookie("ndus=cookie_concurrent_4"),
        terabox_credentials.set_cookie("ndus=cookie_concurrent_5")
    )

    for success, _ in results:
        assert success is True

    # Final DB state must be consistent with in-memory active cookie
    repo = SettingsRepository(temp_db)
    raw_in_db = await repo.get_setting(SETTING_KEY_TERABOX_COOKIE)
    assert raw_in_db is not None
    decrypted_in_db = decrypt_secret(raw_in_db)
    assert decrypted_in_db == terabox_credentials.get_terabox_cookie()
