class WebError(ValueError):
    def __init__(self, code, message, *, status=422, field=None, reload=False):
        super().__init__(message)
        self.code, self.message = code, message
        self.status, self.field, self.reload = status, field, reload

    def packet(self):
        return {'error': {'code': self.code, 'message': self.message,
                          'field': self.field, 'reload_required': self.reload}}
