"""Typed URL-array input for XingAPI v2; no URLs persist in prepared receipts."""
import hashlib
import re
import time

from .xingapi import XingAPIVideoClient
from ..catalog.bindings import validate_request
from ..config.storage import ConfigError
from ..media_references import public_url


class LocalRequestError(ConfigError):
    """A locally rejected request, proven to have made no provider POST."""


class XingAPIReferenceVideoClient(XingAPIVideoClient):
    def _submit(self, *args, **kwargs):
        try:
            return super()._submit(*args, **kwargs)
        except Exception as error:
            self.last_submission = self.sanitize(self.last_submission)
            error.args = (self.sanitize(str(error)),)
            raise

    def create(self, prompt, **kwargs):
        try:
            self.last_submission = self.prepare(prompt, **kwargs)
            fields = self.fields(prompt, kwargs)
        except ConfigError as error:
            raise LocalRequestError(str(error)) from None
        return self.submit_fields(fields)

    def prepare(self, prompt, **kwargs):
        if kwargs.get('primary_reference') is not None or kwargs.get('reference_images') or kwargs.get('references'):
            raise ConfigError('Version two requires typed references with verified HTTPS transports')
        references = kwargs.get('media_references', [])
        operation = kwargs.get('operation', 'reference-to-video' if references else 'text-to-video')
        request = {'operation': operation, 'prompt': prompt, 'seconds': kwargs['seconds'],
            'resolution': kwargs.get('resolution', '480p'), 'aspect_ratio': kwargs.get('aspect_ratio', '16:9'),
            'generate_audio': kwargs.get('generate_audio', False), 'media_references': references}
        report = validate_request(self.binding, request)
        if not prompt.strip():
            report['errors'].append('Prompt must not be empty')
        if not float(kwargs['seconds']).is_integer():
            report['errors'].append('XingAPI duration must be integer seconds')
        if report['errors']:
            raise ConfigError('; '.join(report['errors']))
        clean = [{k: ref[k] for k in ('kind', 'role', 'sha256', 'bytes', 'mime_type', 'duration_seconds',
                  'width', 'height', 'sample_rate', 'channels', 'derivation') if k in ref} for ref in references]
        consumption = {k: 'transmitted' for k in ('model', 'prompt', 'seconds', 'resolution', 'aspect_ratio')}
        for kind, field in [('image', 'images'), ('video', 'videos'), ('audio', 'audios')]:
            consumption[field] = 'transmitted-as-HTTPS-array' if any(r['kind'] == kind for r in clean) else 'omitted-empty'
        consumption['generate_audio'] = ('transmitted' if self.binding.capabilities['audio_control'] == 'explicit'
                                         else self.binding.capabilities['audio_control'])
        consumption['size'] = 'derived-from-resolution-and-aspect-ratio'
        return {'binding_snapshot': self.binding.snapshot(), 'operation': operation, 'remote_model': self.model,
            'prompt': prompt, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'parameters': {k: v for k, v in request.items() if k not in {'prompt', 'media_references'}},
            'media_references': clean, 'parameter_consumption': consumption, 'warnings': report['warnings'],
            'wire_fields': {'seconds': 'duration', 'aspect_ratio': 'ratio', 'image': 'images', 'video': 'videos', 'audio': 'audios'}}

    def fields(self, prompt, kwargs):
        fields = super().fields(prompt, kwargs)
        references = kwargs.get('media_references', [])
        minimum = (self.binding.capabilities.get('media_reference_limits') or {}).get('minimum_url_validity_seconds', 7200)
        for ref in references:
            url = ref.get('url')
            public_url(url)
            if (not ref.get('verification') or ref['verification'].get('sha256') != ref['sha256']
                    or ref['verification'].get('bytes') != ref['bytes']):
                raise ConfigError('Media URL needs full hash verification before creation')
            expiry = ref.get('expires_at')
            if expiry is not None and expiry - time.time() < minimum:
                raise ConfigError('Media URL expires too soon; refresh before creation')
            field = {'image': 'images', 'video': 'videos', 'audio': 'audios'}[ref['kind']]
            fields.setdefault(field, []).append(url)
        return fields

    def sanitize(self, value):
        if isinstance(value, dict):
            value = {key: '[REDACTED]' if key.lower() in {'signature', 'signed_url', 'media_url'} else item
                     for key, item in value.items()}
        value = super().sanitize(value)
        if isinstance(value, str):
            # v2 recovery uses the authenticated /content endpoint, never these
            # echoed input or signed output URLs. Redact without needing expired inputs.
            value = re.sub(r'https?://[^\s<>"\']+', '[REMOTE_URL_REDACTED]', value)
            value = re.sub(r'(?<=/m/)[A-Za-z0-9_-]{43}', '[TOKEN_REDACTED]', value)
        return value

    def query(self, task_id):
        from vc_common import APIError
        try:
            status, body = super().query(task_id)
        except APIError as error:
            error.args = (self.sanitize(str(error)),)
            raise
        return status, self.sanitize(body)
