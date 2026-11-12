#!/usr/bin/env python
# encoding: utf-8

from django.test import TestCase
from rest_framework_simplejwt.tokens import SlidingToken


class AccountTests(TestCase):
    fixtures = ['test/users.json']

    def test_obtain_authtoken_success(self):
        """ Try and login and confirm that the login was successful """
        resp = self.client.post(
            '/api/v1/accounts/obtain-auth-token/',
            {
                'username': 'testuser1',
                'password': 'testpassword'
            }
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['id'] == 1)
        decoded_token = SlidingToken(resp.json()['token'])
        self.assertTrue(int(decoded_token.get("user_id")) == 1)
        self.assertTrue(decoded_token.get('username') == 'testuser1')

    def test_obtain_authtoken_wrong_password(self):
        """ Try and login and confirm that the login was unsuccessful """
        resp = self.client.post(
            '/api/v1/accounts/obtain-auth-token/',
            {
                'username': 'testuser1',
                'password': 'wrongpassword'
            }
        )

        # simplejwt answers bad credentials with 401; djangorestframework-jwt
        # used 400. The front end only branches on success/failure, so this is
        # a status-code change rather than a behaviour change.
        self.assertEqual(resp.status_code, 401)

    def test_refresh_authtoken_keeps_user_id(self):
        """ A refreshed token still carries the id the front end needs """
        resp = self.client.post(
            '/api/v1/accounts/obtain-auth-token/',
            {
                'username': 'testuser1',
                'password': 'testpassword'
            }
        )
        self.assertEqual(resp.status_code, 200)

        refreshed = self.client.post(
            '/api/v1/accounts/refresh-auth-token/',
            {'token': resp.json()['token']}
        )

        self.assertEqual(refreshed.status_code, 200)
        self.assertTrue(refreshed.json()['id'] == 1)
        self.assertTrue(int(SlidingToken(refreshed.json()['token']).get('user_id')) == 1)
