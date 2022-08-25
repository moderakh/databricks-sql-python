# Copyright 2022 Databricks, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"), except
# that the use of services to which certain application programming
# interfaces (each, an "API") connect requires that the user first obtain
# a license for the use of the APIs from Databricks, Inc. ("Databricks"),
# by creating an account at www.databricks.com and agreeing to either (a)
# the Community Edition Terms of Service, (b) the Databricks Terms of
# Service, or (c) another written agreement between Licensee and Databricks
# for the use of the APIs.
#
# You may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
from typing import TypedDict, List

from databricks.sql.auth.oauth import get_tokens, check_and_refresh_access_token
import base64


# Private API: this is an evolving interface and it will change in the future.
# Please must not depend on it in your applications.
from databricks.sql.experimental.oauth_persistence import OAuthToken, OAuthPersistence


class CredentialsProvider:
    def add_headers(self, request_headers: TypedDict):
        pass


# Private API: this is an evolving interface and it will change in the future.
# Please must not depend on it in your applications.
class AccessTokenAuthProvider(CredentialsProvider):
    def __init__(self, access_token: str):
        self.__authorization_header_value = "Bearer {}".format(access_token)

    def add_headers(self, request_headers: TypedDict):
        request_headers['Authorization'] = self.__authorization_header_value


# Private API: this is an evolving interface and it will change in the future.
# Please must not depend on it in your applications.
class BasicAuthProvider(CredentialsProvider):
    def __init__(self, username: str, password: str):
        auth_credentials = f"{username}:{password}".encode("UTF-8")
        auth_credentials_base64 = base64.standard_b64encode(auth_credentials).decode("UTF-8")

        self.__authorization_header_value = f"Basic {auth_credentials_base64}"

    def add_headers(self, request_headers: TypedDict):
        request_headers['Authorization'] = self.__authorization_header_value


# Private API: this is an evolving interface and it will change in the future.
# Please must not depend on it in your applications.
class DatabricksOAuthProvider(CredentialsProvider):
    SCOPE_DELIM = ' '

    def __init__(self, hostname: str, oauth_persistence: OAuthPersistence, client_id: str, scopes: List[str]):
        try:
            self._hostname = self._normalize_host_name(hostname=hostname)
            self._scopes_as_str = DatabricksOAuthProvider.SCOPE_DELIM.join(scopes)
            self._oauth_persistence = oauth_persistence
            self._client_id = client_id
            self._access_token = None
            self._refresh_token = None
            self._initial_get_token()
        except Exception as e:
            logging.error(f"unexpected error", e, exc_info=True)
            raise e

    def add_headers(self, request_headers: TypedDict):
        self._update_token_if_expired()
        request_headers['Authorization'] = f"Bearer {self._access_token}"

    @staticmethod
    def _normalize_host_name(hostname: str):
        maybe_scheme = "https://" if not hostname.startswith("https://") else ""
        maybe_trailing_slash = "/" if not hostname.endswith("/") else ""
        return f"{maybe_scheme}{hostname}{maybe_trailing_slash}"

    def _initial_get_token(self):
        try:
            if self._access_token is None or self._refresh_token is None:
                if self._oauth_persistence:
                    token = self._oauth_persistence.read()
                    if token:
                        self._access_token = token.get_access_token()
                        self._refresh_token = token.get_refresh_token()

            if self._access_token and self._refresh_token:
                self._update_token_if_expired()
            else:
                (access_token, refresh_token) = get_tokens(hostname=self._hostname,
                                                           client_id=self._client_id,
                                                           scope=self._scopes_as_str)
                self._access_token = access_token
                self._refresh_token = refresh_token
                self._oauth_persistence.persist(OAuthToken(access_token, refresh_token))
        except Exception as e:
            logging.error(f"unexpected error in oauth initialization", e, exc_info=True)
            raise e

    def _update_token_if_expired(self):
        try:
            (fresh_access_token, fresh_refresh_token, is_refreshed) = check_and_refresh_access_token(
                hostname=self._hostname,
                client_id=self._client_id,
                access_token=self._access_token,
                refresh_token=self._refresh_token)
            if not is_refreshed:
                return
            else:
                self._access_token = fresh_access_token
                self._refresh_token = fresh_refresh_token

                if self._oauth_persistence:
                    token = OAuthToken(self._access_token, self._refresh_token)
                    self._oauth_persistence.persist(token)
        except Exception as e:
            logging.error(f"unexpected error in oauth token update", e, exc_info=True)
            raise e