#!/usr/bin/env python
# encoding: utf-8

from rest_framework_simplejwt.serializers import (
    TokenObtainSlidingSerializer,
    TokenRefreshSlidingSerializer,
)
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import SlidingToken


# Why sliding tokens rather than simplejwt's default access/refresh pair:
# the old djangorestframework-jwt issued a single token, refreshed by POSTing
# {"token": ...} and getting {"token": ...} back. simplejwt's *sliding* token
# has exactly that shape; its access/refresh pair does not (it wants
# {"refresh": ...} and answers {"access": ...}). Using sliding tokens keeps
# web/modules/common/CustomSuperagent.js working untouched.
#
# Both responses also have to carry the user id: the front end stores the whole
# response body as its user object and treats a falsy `user.id` as logged out,
# including after a refresh. The old library added it through
# JWT_RESPONSE_PAYLOAD_HANDLER, for which simplejwt has no equivalent, so it is
# added here instead.


class OpenEatsTokenObtainSerializer(TokenObtainSlidingSerializer):
    """ Issues a sliding token, plus the user id the front end expects. """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # djangorestframework-jwt put the username in the payload. Nothing in
        # the front end reads it, but it is cheap to keep and the account
        # tests assert on it.
        token['username'] = user.get_username()
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['id'] = self.user.id
        return data


class OpenEatsTokenRefreshSerializer(TokenRefreshSlidingSerializer):
    """ Refreshes a sliding token, keeping the user id in the response. """

    def validate(self, attrs):
        data = super().validate(attrs)
        # Read the id back off the token we just issued rather than tracking it
        # separately: the refresh view never loads the User. simplejwt stores
        # the claim as a string, but the login response and the front end both
        # use the integer pk, so keep the two responses the same shape.
        token = SlidingToken(data['token'])
        user_id = token.get(jwt_settings.USER_ID_CLAIM)
        data['id'] = int(user_id) if user_id is not None else None
        return data
