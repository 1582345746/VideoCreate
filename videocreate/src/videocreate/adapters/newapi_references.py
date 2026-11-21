"""NewAPI v2: verified typed HTTPS inputs, with the original NewAPI read path."""
import hashlib
import re
import time

from .video import BindingVideoClient
from .xingapi_references import LocalRequestError
from ..catalog.bindings import validate_request
from ..config.storage import ConfigError, redact_config
from ..media_references import public_url


class NewAPIReferenceVideoClient(BindingVideoClient):
    def __init__(self, binding):
        import media_client as wire
        super().__init__(binding, wire.NewApiJsonVideoClient(binding.base_url, binding.key, binding.remote_model))

    def prepare(self, prompt, **kwargs):
        if self.binding.options.get('primary_image_field', 'images') != 'images':
            raise ConfigError('NewAPI v2 transmits the images array; first_frame is not this contract')
        if kwargs.get('primary_reference') is not None or kwargs.get('reference_images') or kwargs.get('references'):
            raise ConfigError('NewAPI v2 requires typed references with verified HTTPS transports')
        references = kwargs.get('media_references', [])
        operation = kwargs.get('operation', 'reference-to-video' if references else 'text-to-video')
        request = {'operation': operation, 'prompt': prompt, 'seconds': kwargs['seconds'],
            'resolution': kwargs.get('resolution', '720p'), 'aspect_ratio': kwargs.get('aspect_ratio', '16:9'),
            'generate_audio': kwargs.get('generate_audio', False), 'media_references': references}
        report = validate_request(self.binding, request)
        if not prompt.strip():
            report['errors'].append('Prompt must not be empty')
        if not float(kwargs['seconds']).is_integer():
            report['errors'].append('NewAPI duration must be integer seconds')
        if report['errors']:
            raise ConfigError('; '.join(report['errors']))
        clean = [{k: ref[k] for k in ('kind', 'role', 'sha256', 'bytes', 'mime_type', 'duration_seconds',
                  'width', 'height', 'sample_rate', 'channels', 'derivation') if k in ref} for ref in references]
        consumption = {k: 'transmitted' for k in ('model', 'prompt', 'seconds', 'resolution', 'aspect_ratio')}
        transport = self.binding.options.get('reference_transport', 'https-url')
        for kind, field in [('image', 'images'), ('video', 'videos'), ('audio', 'audios')]:
            consumption[field] = ('transmitted-as-data-URI-array' if transport == 'data-uri' else
                                  'transmitted-as-HTTPS-array') if any(r['kind'] == kind for r in clean) else 'omitted-empty'
        consumption['generate_audio'] = ('transmitted' if self.binding.capabilities['audio_control'] == 'explicit'
                                         else self.binding.capabilities['audio_control'])
        consumption['size'] = 'derived-from-resolution-and-aspect-ratio'
        return {'binding_snapshot': self.binding.snapshot(), 'operation': operation, 'remote_model': self.model,
            'prompt': prompt, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'parameters': {k: v for k, v in request.items() if k not in {'prompt', 'media_references'}},
            'media_references': clean, 'parameter_consumption': consumption, 'warnings': report['warnings'],
            'wire_fields': {'seconds': 'seconds', 'aspect_ratio': 'aspect_ratio',
                            'image': 'images', 'video': 'videos', 'audio': 'audios'}}

    def fields(self, prompt, kwargs):
        fields = {'model': self.model, 'prompt': prompt, 'seconds': int(kwargs['seconds']),
                  'aspect_ratio': kwargs.get('aspect_ratio', '16:9'), 'resolution': kwargs.get('resolution', '720p')}
        if self.binding.capabilities['audio_control'] == 'explicit':
            fields['generate_audio'] = bool(kwargs.get('generate_audio', False))
        minimum = (self.binding.capabilities.get('media_reference_limits') or {}).get('minimum_url_validity_seconds', 7200)
        inline = self.binding.options.get('reference_transport', 'https-url') == 'data-uri'
        if inline:
            from .inline_media import MAX_INLINE_BYTES, data_uri
            if sum(ref.get('bytes', 0) for ref in kwargs.get('media_references', [])) > MAX_INLINE_BYTES:
                raise ConfigError('Inline reference payload exceeds 32 MiB local limit')
        for ref in kwargs.get('media_references', []):
            if inline:
                field = {'image': 'images', 'video': 'videos', 'audio': 'audios'}[ref['kind']]
                fields.setdefault(field, []).append(data_uri(ref))
                continue
            public_url(ref.get('url'))
            if (not ref.get('verification') or ref['verification'].get('sha256') != ref['sha256']
                    or ref['verification'].get('bytes') != ref['bytes']):
                raise ConfigError('Media URL needs full hash verification before creation')
            if ref.get('expires_at') is not None and ref['expires_at'] - time.time() < minimum:
                raise ConfigError('Media URL expires too soon; refresh before creation')
            field = {'image': 'images', 'video': 'videos', 'audio': 'audios'}[ref['kind']]
            fields.setdefault(field, []).append(ref['url'])
        return fields

    def sanitize(self, value, *, output_url=False):
        # Only result URL fields survive for download recovery. Input arrays and
        # echoed request objects must never become output fallback candidates.
        if isinstance(value, dict):
            return {k: ('[REDACTED]' if k.lower() in {
                'images', 'videos', 'audios', 'media_references', 'references', 'request', 'input', 'inputs', 'echo',
                'signature', 'signed_url', 'media_url'} else self.sanitize(v, output_url=k in {
                    'url', 'video_url', 'videoUrl', 'download_url', 'downloadUrl', 'output_url', 'result_url', 'resultUrl'}))
                for k, v in redact_config(value).items()}
        if isinstance(value, list):
            return [self.sanitize(v) for v in value]
        if isinstance(value, str):
            value = re.sub(r'data:[^\s;,]+;base64,[A-Za-z0-9+/=_-]+', '[INLINE_MEDIA_REDACTED]', value)
            if self.binding.key:
                value = value.replace(self.binding.key, '[REDACTED]')
            if not output_url:
                value = re.sub(r'https?://[^\s<>"\']+', '[REMOTE_URL_REDACTED]', value)
                value = re.sub(r'(?<=/m/)[A-Za-z0-9_-]{43}', '[TOKEN_REDACTED]', value)
        return value

    def create(self, prompt, **kwargs):
        import media_client as wire
        from provider_contracts import SubmissionUnknownError, task_id
        try:
            self.last_submission = self.prepare(prompt, **kwargs)
            fields = self.fields(prompt, kwargs)
        except ConfigError as error:
            raise LocalRequestError(self.sanitize(str(error))) from None
        try:
            response = self._submit('POST', wire.api_url(self.base_url, '/v1/videos'), key=self.binding.key,
                value=fields, timeout=self.binding.options.get('request_timeout_seconds', 120))
        except Exception as error:
            self.last_submission = self.sanitize(self.last_submission)
            error.args = (self.sanitize(str(error)),)
            raise
        self.last_submission['create_response'] = self.sanitize(response)
        created = task_id(response, keys=self.binding.options.get('task_id_fields', ['task_id', 'taskId', 'job_id', 'jobId', 'id']))
        if not created:
            raise SubmissionUnknownError('Create response has no protocol task ID; hold and reconcile, do not resubmit')
        return created

    def query(self, task_id):
        from provider_contracts import task_status, is_completed
        try:
            _, body = self.reader.query(task_id)
        except Exception as error:
            error.args = (self.sanitize(str(error)),)
            raise
        body = self.sanitize(body)
        status = task_status(body)
        return status or ('completed' if is_completed(body) else 'unknown'), body

    def poll(self, task_id, *, timeout_seconds, on_status=None):
        import media_client as wire
        # Reuse polling/retry policy, but dispatch through our sanitized query.
        return wire.NewApiJsonVideoClient.poll(self, task_id, timeout_seconds=timeout_seconds, on_status=on_status)

    def download(self, task_id, status_payload, destination):
        return self.reader.download(task_id, self.sanitize(status_payload), destination)
