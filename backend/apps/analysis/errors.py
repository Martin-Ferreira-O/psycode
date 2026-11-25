class ProviderError(RuntimeError):
    pass


class AnalysisRetry(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class SubmissionUncertain(ProviderError):
    pass


class JevContextLimit(ProviderError):
    pass
