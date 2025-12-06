import asyncio
import random
from typing import Any, Dict, List, Optional, Union

import noble_tls
from noble_tls import Client as NobleClient
import noble_tls.response
import requests

from .exceptions import MaxRetriesExceeded
from .utils import exponential_backoff

from loguru import logger


class NobleTLSClient:
    def __init__(
        self,
        proxies: Optional[List[str]] = None,
        client_identifier: str = NobleClient.CHROME_111,
        random_tls_extension_order: bool = True,
        max_retries: int = 5,
        backoff_base: float = 0.5,
        backoff_factor: float = 2.0,
        max_backoff: float = 60.0,
        # Advanced TLS and HTTP/2 settings
        ja3_string: Optional[str] = None,
        h2_settings: Optional[Dict[str, Any]] = None,
        h2_settings_order: Optional[List[str]] = None,
        supported_signature_algorithms: Optional[List[str]] = None,
        supported_delegated_credentials_algorithms: Optional[List[str]] = None,
        supported_versions: Optional[List[str]] = None,
        key_share_curves: Optional[List[str]] = None,
        cert_compression_algo: Optional[str] = None,
        additional_decode: Optional[str] = None,
        pseudo_header_order: Optional[List[str]] = None,
        connection_flow: Optional[int] = None,
        priority_frames: Optional[List[Dict[str, Any]]] = None,
        header_order: Optional[List[str]] = None,
        header_priority: Optional[Dict[str, Any]] = None,
        force_http1: bool = False,
        catch_panics: bool = False,
        debug: bool = False,
        transportOptions: Optional[Dict[str, Any]] = None,
        connectHeaders: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the NobleTLSClient.

        :param proxies: Optional list of proxy URLs.
        :param client_identifier: Identifier for the TLS client.
        :param random_tls_extension_order: Whether to randomize TLS extension order.
        :param max_retries: Maximum number of retry attempts.
        :param backoff_base: Base delay for exponential backoff.
        :param backoff_factor: Factor for exponential backoff.
        :param max_backoff: Maximum delay for exponential backoff.
        :param ja3_string: Custom JA3 string for TLS fingerprinting.
        :param h2_settings: HTTP/2 settings.
        :param h2_settings_order: Order of HTTP/2 settings.
        :param supported_signature_algorithms: List of supported signature algorithms.
        :param supported_delegated_credentials_algorithms: List of supported delegated credentials algorithms.
        :param supported_versions: Supported TLS versions.
        :param key_share_curves: Supported key share curves.
        :param cert_compression_algo: Certificate compression algorithm.
        :param additional_decode: Additional decode algorithm.
        :param pseudo_header_order: Order of pseudo-headers in HTTP/2.
        :param connection_flow: Connection flow/window size increment.
        :param priority_frames: Priority frames for HTTP/2.
        :param header_order: Order of headers in requests.
        :param header_priority: Priority settings for headers.
        :param force_http1: Force the use of HTTP/1.1 instead of HTTP/2.
        :param catch_panics: Catch panics to avoid stack traces on critical errors.
        :param debug: Enable debug mode.
        """
        self.proxies = proxies or []
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff

        self.client_identifier = client_identifier
        self.random_tls_extension_order = random_tls_extension_order

        # Initialize noble_tls.Session with all advanced parameters
        self.session = noble_tls.Session(
            client=self.client_identifier,
            ja3_string=ja3_string,
            h2_settings=h2_settings,
            h2_settings_order=h2_settings_order,
            supported_signature_algorithms=supported_signature_algorithms,
            supported_delegated_credentials_algorithms=supported_delegated_credentials_algorithms,
            supported_versions=supported_versions,
            key_share_curves=key_share_curves,
            cert_compression_algo=cert_compression_algo,
            additional_decode=additional_decode,
            pseudo_header_order=pseudo_header_order,
            connection_flow=connection_flow,
            priority_frames=priority_frames,
            header_order=header_order,
            header_priority=header_priority,
            random_tls_extension_order=self.random_tls_extension_order,
            force_http1=force_http1,
            catch_panics=catch_panics,
            debug=debug,
        )

        logger.info(f"Initialized NobleTLSClient with client identifier '{self.client_identifier}'.")

    async def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        allow_redirects: bool = True,
        insecure_skip_verify: bool = False,
        timeout: Optional[float] = None,
    ) -> noble_tls.response.Response:
        """
        Make an HTTP request with retries and optional proxy rotation.

        :param method: HTTP method (GET, POST, etc.).
        :param url: Target URL.
        :param headers: Request headers.
        :param params: Query parameters.
        :param data: Request body.
        :param json_data: JSON payload.
        :param cookies: Cookies to include.
        :param allow_redirects: Whether to follow redirects.
        :param insecure_skip_verify: Whether to skip TLS certificate verification.
        :param timeout: Request timeout in seconds.
        :return: noble_tls Response object.
        :raises MaxRetriesExceeded: If all retry attempts fail.
        """
        attempt = 0
        while attempt <= self.max_retries:
            proxy = random.choice(self.proxies) if self.proxies else None
            try:
                response = await self.session.execute_request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    params=params,
                    data=data,
                    json=json_data,
                    cookies=cookies,
                    proxy=proxy,
                    allow_redirects=allow_redirects,
                    insecure_skip_verify=insecure_skip_verify,
                    timeout_seconds=timeout
                )

                if response.status_code in {429, 500, 502, 503, 504}:
                    logger.warning(f"Received status code {response.status_code} for URL: {url}. Retrying...")
                    raise noble_tls.HTTPStatusError(
                        f"Status code {response.status_code}", request=response.request, response=response
                    )

                logger.info(f"Successfully fetched URL: {url} with status code {response.status_code}.")
                return response

            except requests.exceptions.HTTPError as e:
                logger.error(f"Request error on attempt {attempt + 1} for URL: {url} - {str(e)}")
                if attempt == self.max_retries:
                    logger.error(f"Max retries exceeded for URL: {url}")
                    raise MaxRetriesExceeded(f"Failed to fetch {url} after {self.max_retries} attempts.") from e

                delay = exponential_backoff(attempt, self.backoff_base, self.backoff_factor, self.max_backoff)
                logger.info(f"Waiting for {delay} seconds before retrying...")
                await asyncio.sleep(delay)
                attempt += 1

        # If all retries fail, raise exception
        raise MaxRetriesExceeded(f"Failed to fetch {url} after {self.max_retries} attempts.")

    # Convenience methods

    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> noble_tls.response.Response:
        """Convenience method for GET requests."""
        return await self.request("GET", url, headers=headers, params=params, cookies=cookies, **kwargs)

    async def post(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> noble_tls.response.Response:
        """Convenience method for POST requests."""
        return await self.request("POST", url, headers=headers, params=params, data=data, json_data=json_data, cookies=cookies, **kwargs)

    async def put(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> noble_tls.response.Response:
        """Convenience method for PUT requests."""
        return await self.request("PUT", url, headers=headers, params=params, data=data, json_data=json_data, cookies=cookies, **kwargs)

    async def delete(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> noble_tls.response.Response:
        """Convenience method for DELETE requests."""
        return await self.request("DELETE", url, headers=headers, params=params, cookies=cookies, **kwargs)

    async def head(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> noble_tls.response.Response:
        """Convenience method for HEAD requests."""
        return await self.request("HEAD", url, headers=headers, params=params, cookies=cookies, **kwargs)

    async def options(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> noble_tls.response.Response:
        """Convenience method for OPTIONS requests."""
        return await self.request("OPTIONS", url, headers=headers, params=params, cookies=cookies, **kwargs)

    async def patch(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> noble_tls.response.Response:
        """Convenience method for PATCH requests."""
        return await self.request("PATCH", url, headers=headers, params=params, data=data, json_data=json_data, cookies=cookies, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
