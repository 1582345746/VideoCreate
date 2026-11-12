"""Versioned XingAPI asynchronous contracts; v1 stays text-only for old tasks."""
from __future__ import annotations

import copy
import itertools
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from .video import BindingVideoClient
from ..config.storage import ConfigError, redact_config


def unwrap(body):
    return body['data'] if isinstance(body.get('data'), dict) else body


def retry_delay(value, default):
    try:
        seconds = int(value)
    except (ValueError, TypeError):
        try:
            instant = parsedate_to_datetime(value)
            seconds = (instant - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return default
    return max(default, seconds)


class XingAPIVideoClient(BindingVideoClient):
    def __init__(self, binding):
        import media_client as wire
        super().__init__(binding, wire.Sub2ApiVideoClient(binding.base_url, binding.key, binding.remote_model))

    def prepare(self, prompt, **kwargs):
        if kwargs.get('media_references'):
            raise ConfigError('Typed HTTPS media references require the version two adapter')
        primary, extra = self._split_references(kwargs.get('primary_reference'), kwargs.get('reference_images', ()), kwargs.get('references'))
        if primary is not None or extra:
            raise ConfigError('XingAPI requires HTTPS media URL arrays; local reference upload/mapping is not configured')
        result = super().prepare(prompt, **kwargs)
        if not float(kwargs['seconds']).is_integer():
            raise ConfigError('XingAPI duration must be integer seconds')
        result['wire_fields'] = {'seconds': 'duration', 'aspect_ratio': 'ratio', 'resolution': 'resolution'}
        return result

    def fields(self, prompt, kwargs):
        fields = {'model': self.model, 'prompt': prompt, 'duration': int(kwargs['seconds']),
                  'ratio': kwargs.get('aspect_ratio', '16:9'), 'resolution': kwargs.get('resolution', '480p')}
        if self.binding.capabilities['audio_control'] == 'explicit':
            fields['generate_audio'] = bool(kwargs.get('generate_audio', False))
        return fields

    def sanitize(self, value):
        if isinstance(value, str):
            return value.replace(self.binding.key, '[REDACTED]') if self.binding.key else value
        if isinstance(value, dict):
            return {k: self.sanitize(v) for k, v in redact_config(value).items()}
        if isinstance(value, list):
            return [self.sanitize(v) for v in value]
        return value

    def create(self, prompt, **kwargs):
        self.last_submission = self.prepare(prompt, **kwargs)
        fields = self.fields(prompt, kwargs)
        return self.submit_fields(fields)

    def submit_fields(self, fields):
        import media_client as wire
        from provider_contracts import SubmissionUnknownError
        response = self._submit('POST', wire.api_url(self.base_url, '/v1/videos/generations'),
                                key=self.binding.key, value=fields,
                                timeout=self.binding.options.get('request_timeout_seconds', 120))
        self.last_submission['create_response'] = self.sanitize(copy.deepcopy(response))
        body = unwrap(response)
        for key in ('id', 'task_id', 'request_id'):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value  # Keep the original value, including videoprep_ prefix.
        raise SubmissionUnknownError('XingAPI create returned no task ID; preserve receipt and reconcile without resubmitting')

    def query(self, task_id):
        import media_client as wire
        body = unwrap(wire.request_json('GET', wire.api_url(self.base_url, '/v1/videos/' + quote(task_id, safe='')),
                                       key=self.binding.key, timeout=60))
        return str(body.get('status', '')).strip().lower() or 'unknown', body

    def poll(self, task_id, *, timeout_seconds, on_status=None):
        from vc_common import APIError, SkillError
        from provider_contracts import COMPLETED_STATES, FAILED_STATES, ProviderTaskFailedError, task_error
        deadline = time.monotonic() + timeout_seconds
        for delay in itertools.cycle((10, 30, 60)):
            wait = delay
            try:
                status, body = self.query(task_id)
            except APIError as error:
                if error.status not in {404, 408, 425, 429, 500, 502, 503, 504}:
                    raise
                wait = retry_delay(error.retry_after, wait)
                status, body = 'read_pending', {'warning': str(error), 'retry_after_seconds': wait}
            except (SkillError, OSError) as error:
                status, body = 'read_pending', {'warning': str(error)}
            if on_status:
                on_status(status, body)
            if status in FAILED_STATES:
                raise ProviderTaskFailedError(str(body.get('error_message') or task_error(body)), status=status)
            if status in COMPLETED_STATES:
                return body
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('XingAPI polling stopped locally; resume the same task ID')
            time.sleep(min(wait, remaining))
            if time.monotonic() >= deadline:
                raise TimeoutError('XingAPI polling stopped locally; resume the same task ID')

    def download(self, task_id, status_payload, destination):
        import media_client as wire
        from provider_contracts import COMPLETED_STATES
        if str(status_payload.get('status', '')).strip().lower() not in COMPLETED_STATES:
            raise ConfigError('XingAPI download requires a confirmed completed task')
        # The authenticated endpoint refreshes temporary links on every retry.
        # urllib's unredirected Authorization is never forwarded to storage.
        wire.download_file(wire.api_url(self.base_url, '/v1/videos/' + quote(task_id, safe='') + '/content'),
                           destination, key=self.binding.key, timeout=300,
                           expected_content_types=('video/', 'application/octet-stream'))
        try:
            wire.assert_mp4(destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
