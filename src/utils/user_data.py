# import Python's standard libraries
import re
import abc
import json
import base64
import pathlib
import warnings
import binascii
import threading
from typing import Optional, Any, Union

# import local files
if (__name__ == "__main__"):
    from errors import APIServerError
    from cryptography_operations import *
    from constants import CONSTANTS as C
    from spinner import Spinner
    from schemas import CookieSchema, APIKeyResponse, APIKeyIDResponse, APICsrfResponse
    from functional import validate_schema, save_key_prompt
else:
    from .errors import APIServerError
    from .cryptography_operations import *
    from .constants import CONSTANTS as C
    from .spinner import Spinner
    from .schemas import CookieSchema, APIKeyResponse, APIKeyIDResponse, APICsrfResponse
    from .functional import validate_schema, save_key_prompt

# Import Third-party Libraries
import httpx
from pydantic import BaseModel

# Note: the cryptography library should have been
# installed upon import of cryptography_operations.py
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import types
from cryptography.hazmat.primitives import serialization

class UserData(abc.ABC):
    """Creates a way to securely deal with the user's data
    that is stored on the user's machine.

    Requires the following methods 
    to be overridden in the child class:
        - save_data
        - load_data

    The data stored on the user's machine is encrypted client-side using ChaCha20-Poly1305.
    However, the user can opt to store their generated secret key on Cultured Downloader API
    or on their own machine if they wish for a faster loading time.

    During transmission to Cultured Downloader API, the user's secret key or key ID token
    is encrypted using asymmetric encryption on top of HTTPS as a form of layered security.
    Note that the RSA key pair is generated within the 
    current application execution and is not stored on the user's machine.
    """
    def __init__(self, data_path: pathlib.Path, data: Optional[Any] = None) -> None:
        """Constructor for the UserData class.

        Attributes:
            data_path (pathlib.Path):
                The path to the file where the data is stored.
            data (Any, Optional): 
                The data to be handled. If None, the data will be loaded 
                from the saved file in the application's directory via the
                load_data method that must be configured in the child class.
        """
        key_pair = generate_rsa_key_pair()
        self.__private_key = key_pair[0].decode("utf-8")
        self.__public_key = key_pair[1].decode("utf-8")
        self.__client_digest_method = "sha512"  if (C.IS_64BITS) \
                                                else "sha256"
        self.__server_digest_method = "sha512"  if (self.__client_digest_method == "sha512") \
                                                else "sha256"

        if (not isinstance(data_path, pathlib.Path)):
            raise TypeError(f"Expected pathlib.Path object, got {type(data_path)} for data_path argument.")
        self.__data_path = data_path

        self.__secret_key = self.__load_key()
        if (data is None):
            self.data = self.load_data()
        else:
            self.data = data

    def encrypt_data(self, data: Optional[Any] = None) -> None:
        """Encrypts the cookie data to the user's machine in a file."""
        self.__data_path.parent.mkdir(parents=True, exist_ok=True)

        if (data is None):
            data = self.data
        encrypted_data, nonce = chacha_encrypt(plaintext=data, key=self.secret_key)

        encoded_data = base64.b64encode(encrypted_data)
        nonce = base64.b64encode(nonce)
        with open(self.__data_path, "w") as f:
            f.write(".".join((encoded_data.decode("utf-8"), nonce.decode("utf-8"))))

    def decrypt_data(self, decode: Optional[bool] = True, schema: Optional[BaseModel] = None, 
                     regex: Optional[re.Pattern] = None) -> Union[bytes, str, dict, None]:
        """Decrypt the cookie data from the user's machine from the saved file.

        Args:
            decode (bool):
                Whether to decode the plaintext from bytes to a string. 
                (Must be True if validating against a schema or a regex.)
            schema (BaseModel):
                The schema to validate the data against.
                (Will parse the decrypted data into a dictionary if not None.)
            regex (re.Pattern):
                The regex pattern to validate the data against.

        Returns:
            bytes | str | dict | None: 
                The data or None if the file does not exist or is invalid.
        """
        if (schema is not None and regex is not None):
            raise ValueError("Cannot validate against both schema and regex at the same time")

        if (not decode and (schema is not None or regex is not None)):
            warnings.warn("Cannot validate schema/regex if decode is False. Hence, decode will be set to True.")
            decode = True

        if (not self.__data_path.exists() or not self.__data_path.is_file()):
            return

        with open(self.__data_path, "r") as f:
            try:
                encrypted_data, nonce = f.read().split(sep=".")
            except (ValueError):
                raise APIServerError("Invalid data...")

        try:
            encrypted_data = base64.b64decode(encrypted_data)
            nonce = base64.b64decode(nonce)
        except (binascii.Error, TypeError, ValueError):
            raise APIServerError("Invalid data...")

        try:
            decrypted_data = chacha_decrypt(
                ciphertext=encrypted_data, 
                key=self.secret_key, 
                nonce=nonce
            )
        except (InvalidTag):
            self.__data_path.unlink()
            return

        if (decode):
            decrypted_data = decrypted_data.decode("utf-8")

        if (regex is not None):
            if (regex.match(decrypted_data) is None):
                self.__data_path.unlink()
                return

        if (schema is not None):
            try:
                decrypted_data = json.loads(decrypted_data)
            except (json.JSONDecodeError):  
                self.__data_path.unlink()
                return

            if (not validate_schema(schema, decrypted_data)):
                self.__data_path.unlink()
                return

        return decrypted_data

    @abc.abstractmethod
    def save_data(self) -> None:
        """Saves the data to the user's machine."""
        pass

    @abc.abstractmethod
    def load_data(self) -> None:
        """Loads the data from the user's machine from the saved file."""
        pass

    def prepare_data_for_transmission(self, data: Union[str, bytes]) -> str:
        """Prepares the data for transmission to the server by encrypting the payload
        using the public key obtained from Cultured Downloader API.

        Args:
            data (str | bytes): 
                The data to be transmitted for encryption.

        Returns:
            str: 
                The encrypted data to sent to Cultured Downloader API for symmetric encryption.
        """
        return base64.b64encode(
            rsa_encrypt(plaintext=data, digest_method=self.server_digest_method)
        ).decode("utf-8")

    def read_api_response(self, received_data: str) -> bytes:
        """Reads the response from the server and decrypts the data.

        Args:
            received_data (str): 
                The data received from the server.
        """
        return rsa_decrypt(
            ciphertext=base64.b64decode(received_data), 
            private_key=self.format_private_key(), 
            digest_method=self.server_digest_method
        )

    def format_private_key(self) -> types.PRIVATE_KEY_TYPES:
        """Formats the private key for use in the asymmetric encryption."""
        return serialization.load_pem_private_key(
            data=self.private_key.encode("utf-8"),
            password=None,
            backend=default_backend(),
        )

    def format_public_key(self) -> types.PUBLIC_KEY_TYPES:
        """Formats the public key for use in the asymmetric encryption."""
        return serialization.load_pem_public_key(
            data=self.publicKey.encode("utf-8"),
            backend=default_backend(),
        )

    def get_csrf_token(self) -> tuple:
        """Gets the CSRF token from the server.

        Returns:
            The CSRF token (str) and the session cookie with the CSRF token.
        """
        with httpx.Client(http2=True, headers=C.REQ_HEADERS, timeout=30) as client:
            res = client.get(f"{C.API_URL}/csrf-token")

        if (res.status_code not in (200, 404)):
            raise APIServerError(f"Server Response: {res.status_code}\n{res.text}")

        cookies = res.cookies
        json_data = res.json()
        if ("error" in json_data):
            raise APIServerError(json_data["error"])
        if (not validate_schema(schema=APICsrfResponse, data=json_data)):
            raise APIServerError("Invalid JSON format response from server...")

        return json_data["csrf_token"], cookies

    def __load_key(self) -> bytes:
        """Loads the secret symmetric key from the API or locally"""
        secret_key_path = C.SECRET_KEY_PATH
        if (secret_key_path.exists() and secret_key_path.is_file()):
            with open(secret_key_path, "rb") as f:
                return f.read()

        key_id_token_path = C.KEY_ID_TOKEN_JSON_PATH
        key_id_token = None
        if (key_id_token_path.exists() and key_id_token_path.is_file()):
            with open(key_id_token_path, "r") as f:
                try:
                    key_id_token = json.load(f).get("key_id_token")
                except (json.JSONDecodeError, TypeError):
                    pass

        if (key_id_token is None):
            return generate_chacha20_key()

        csrf_token, cookies = self.get_csrf_token()
        json_data = {
            "csrf_token":
                csrf_token,
            "server_digest_method": 
                self.__server_digest_method,
            "client_public_key":
                self.__public_key,
            "client_digest_method":
                self.__client_digest_method,
            "key_id_token":
                self.prepare_data_for_transmission(
                    data=key_id_token
                )
        }
        with httpx.Client(http2=True, headers=C.JSON_REQ_HEADERS, cookies=cookies, timeout=30) as client:
            res = client.post(f"{C.API_URL}/get-key", json=json_data)

        if (res.status_code not in (200, 404, 400)):
            raise APIServerError(f"Server Response: {res.status_code}\n{res.text}")

        if (res.status_code == 404):
            # happens when the key_id_token 
            # has expired or is invalid
            key_id_token_path.unlink()
            return generate_chacha20_key()

        json_data = res.json()
        if ("error" in json_data):
            raise APIServerError(json_data["error"])
        if (not validate_schema(schema=APIKeyResponse, data=json_data)):
            raise APIServerError("Invalid JSON format response from server...")

        secret_key = self.read_api_response(json_data["secret_key"])
        return secret_key

    def save_key(self, save_locally: Optional[bool] = False) -> None:
        """Saves the secret symmetric key to the API or locally.

        Args:
            save_locally (bool, optional):
                Whether to save the key locally or not. Defaults to False.

        Returns:
            None
        """
        # Check if the key was already saved locally
        if (C.SECRET_KEY_PATH.exists() and C.SECRET_KEY_PATH.is_file()):
            with open(C.SECRET_KEY_PATH, "rb") as f:
                if (f.read() == self.secret_key):
                    return

        # Check if the key was already saved on the API
        if (C.KEY_ID_TOKEN_JSON_PATH.exists() and C.KEY_ID_TOKEN_JSON_PATH.is_file()):
            return

        if (save_locally):
            with open(C.SECRET_KEY_PATH, "wb") as f:
                f.write(self.__secret_key)

        csrf_token, cookies = self.get_csrf_token()
        json_data = {
            "csrf_token":
                csrf_token,
            "server_digest_method": 
                self.__server_digest_method,
            "client_public_key":
                self.__public_key,
            "client_digest_method":
                self.__client_digest_method,
            "secret_key":
                self.prepare_data_for_transmission(
                    data=self.__secret_key
                )
        }

        with httpx.Client(http2=True, headers=C.JSON_REQ_HEADERS, cookies=cookies, timeout=30) as client:
            res = client.post(f"{C.API_URL}/save-key", json=json_data)

        if (res.status_code not in (200, 400)):
            raise APIServerError(f"Server Response: {res.status_code}\n{res.text}")

        res = res.json()
        if ("error" in res):
            raise APIServerError(res["error"])
        if (not validate_schema(schema=APIKeyIDResponse, data=res)):
            raise APIServerError("Invalid JSON format response from server...")

        key_id_token = rsa_decrypt(
            ciphertext=base64.b64decode(res["key_id_token"]),
            private_key=self.format_private_key(),
            digest_method=self.client_digest_method,
            decode=True
        )
        with open(C.KEY_ID_TOKEN_JSON_PATH, "w") as f:
            json.dump({"key_id_token": key_id_token}, f, indent=4)

    @property
    def secret_key(self) -> bytes:
        return self.__secret_key

    @property
    def private_key (self) -> str:
        return self.__private_key

    @property
    def public_key(self) -> str:
        return self.__public_key

    @property
    def client_digest_method(self) -> str:
        return self.__client_digest_method

    @property
    def server_digest_method(self) -> str:
        return self.__server_digest_method

    def __str__(self) -> str:
        return str(self.data)

    def __repr__(self) -> str:
        return f"Data<{self.data}>"

def convert_website_to_path(website: str) -> pathlib.Path:
    """Converts a website to a path.

    Args:
        website (str): 
            The website to convert.

    Returns:
        pathlib.Path: 
            The path of the website.
    """
    path_table = {
        "fantia": C.FANTIA_COOKIE_PATH,
        "pixiv_fanbox": C.PIXIV_FANBOX_COOKIE_PATH,
    }
    if (website not in path_table):
        raise ValueError(f"Invalid website: {website}")
    return path_table[website]

class SecureCookie(UserData):
    """Creates a way to securely deal with the user's saved
    cookies that is stored on the user's machine."""
    def __init__(self, website: str, cookie_data: Optional[dict] = None) -> None:
        """Initializes the SecureCookie class.

        Args:
            website (str):
                The website that the cookie data is for.
            cookie_data (dict, Optional): 
                The cookie data to be handled. If None, the cookie data will be loaded 
                from the saved file in the application's directory.
        """
        if (not isinstance(cookie_data, Union[None, dict])):
            raise TypeError("cookie_data must be of type dict or None")

        self.__website = website
        super().__init__(
            data=cookie_data, 
            data_path=convert_website_to_path(self.__website)
        )

    def save_data(self) -> None:
        """Saves the data to the user's machine."""
        return self.encrypt_data(data=json.dumps(self.data))

    def load_data(self) -> Union[dict, None]:
        """Loads the data from the user's machine from the saved file."""
        return self.decrypt_data(decode=True, schema=CookieSchema)

    def __str__(self) -> str:
        return json.dumps(self.data)

    def __repr__(self) -> str:
        return f"Cookie<{self.data}>"

def convert_to_readable_format(website: str) -> str:
    """Converts a website string to a readable format.

    Args:
        website (str): 
            The website to convert.

    Returns:
        str: 
            The readable format of the website.
    """
    readable_table = {
        "fantia": "Fantia",
        "pixiv_fanbox": "Pixiv Fanbox",
    }
    if (website not in readable_table):
        raise ValueError(f"Invalid website: {website}")
    return readable_table[website]

class SecureGDriveAPIKey(UserData):
    """Creates a way to securely deal with the user's saved
    Google Drive API key that is stored on the user's machine."""
    def __init__(self, api_key: Optional[str] = None) -> None:
        """Initializes the SecureGDriveAPIKey class.

        Args:
            api_key (str, Optional): 
                The API key data to be handled. If None, the API key data will be loaded 
                from the saved file in the application's directory.
        """
        if (not isinstance(api_key, Union[None, str])):
            raise TypeError("api_key must be of type str or None")

        super().__init__(
            data=api_key, 
            data_path=C.GOOGLE_DRIVE_API_KEY_PATH
        )

    def save_data(self) -> None:
        """Saves the data to the user's machine."""
        return self.encrypt_data(data=self.data)

    def load_data(self) -> Union[dict, None]:
        """Loads the data from the user's machine from the saved file."""
        return self.decrypt_data(decode=True, regex=C.GOOGLE_API_KEY_REGEX)

    def __str__(self) -> str:
        return json.dumps(self.data)

    def __repr__(self) -> str:
        return f"GDriveAPIKey<{self.data}>"

def save_gdrive_api_key(api_key: str) -> None:
    """Save the Google Drive API key.

    Args:
        api_key (str):
            The Google Drive API key to save.

    Returns:
        None
    """
    save_key_locally = save_key_prompt()
    with Spinner(
        message="Saving Google Drive API Key...",
        colour="light_yellow",
        spinner_position="left",
        spinner_type="arc"
    ):
        gdrive_api_key_obj = SecureGDriveAPIKey(api_key)
        gdrive_api_key_obj.save_key(save_locally=save_key_locally)
        gdrive_api_key_obj.save_data()

@Spinner(
    message="Loading Google Drive API Key...",
    colour="light_yellow",
    spinner_position="left",
    spinner_type="arc"
)
def load_gdrive_api_key() -> Union[None, str]:
    """Load the Google Drive API key.

    Returns:
        None | str: 
            The Google Drive API key if it exists, None otherwise.
    """
    if (not C.GOOGLE_DRIVE_API_KEY_PATH.exists() or not C.GOOGLE_DRIVE_API_KEY_PATH.is_file()):
        return

    with open(C.GOOGLE_DRIVE_API_KEY_PATH, "rb") as f:
        encrypted_api_key = f.read()
    return SecureGDriveAPIKey(encrypted_api_key).data

class SaveCookieThread(threading.Thread):
    """Thread to securely save the cookie to a file."""
    def __init__(self, cookie: dict, website: str, save_locally: bool):
        """Constructor for the SaveCookieThread class.

        Attributes:
            cookie (dict):
                The cookie to save.
            website (str):
                The website to save the cookie for.
            save_locally (bool):
                Whether to save the cookie locally or on Cultured Downloader API.
        """
        super().__init__()
        self.cookie = cookie
        self.website = website
        self.readable_website = convert_to_readable_format(self.website)
        self.save_locally = save_locally
        self.result = None

    def run(self) -> None:
        try:
            secure_cookie = SecureCookie(website=self.website, cookie_data=self.cookie)
            secure_cookie.save_key(save_locally=self.save_locally)
        except (APIServerError, httpx.ReadTimeout, httpx.ConnectTimeout):
            self.result = False

        secure_cookie.save_data()
        self.result = True

class LoadCookieThread(threading.Thread):
    """Thread to securely load the cookie from a file."""
    def __init__(self, website: str):
        """Constructor for the LoadCookieThread class.

        Attributes:
            website (str):
                The website to load the cookie for.
        """
        super().__init__()
        self.website = website
        self.readable_website = convert_to_readable_format(self.website)
        self.result = None

    def run(self) -> None:
        try:
            secure_cookie = SecureCookie(website=self.website)
        except (APIServerError, httpx.ReadTimeout, httpx.ConnectTimeout):
            self.result = False

        self.result = secure_cookie.data

def load_cookie(website: str) -> Union[None, LoadCookieThread]:
    """Loads the cookie from the user's machine.

    Args:
        website (str):
            The website to load the cookie for.

    Returns:
        dict | None:
            The cookie data if it exists, otherwise None.
    """
    cookie_path = convert_website_to_path(website)
    if (not cookie_path.exists() or not cookie_path.is_file()):
        return None

    load_cookie_thread = LoadCookieThread(website=website)
    load_cookie_thread.start()
    return load_cookie_thread

__all__ = [
    "load_cookie",
    "SecureCookie",
    "SecureGDriveAPIKey",
    "SaveCookieThread",
    "LoadCookieThread",
    "save_gdrive_api_key",
    "load_gdrive_api_key",
    "convert_website_to_path",
    "convert_to_readable_format",
]

# test codes
if (__name__ == "__main__"):
    # Google API key from random repo on GitHub
    # t = SecureGDriveAPIKey("AIzaSyBxZMqLD3wMDMItNtV45E7aPVZCPsS2jGg")
    # t.save_key(save_locally=False)
    # t.save_data()

    s = SecureGDriveAPIKey()
    print(s.data)