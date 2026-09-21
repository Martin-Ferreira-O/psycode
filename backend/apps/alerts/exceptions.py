class AlertAlreadyExists(Exception):
    def __init__(self, alerta_id):
        super().__init__(alerta_id)
        self.alerta_id = alerta_id


class AlertNotFound(Exception):
    def __init__(self, alerta_id):
        super().__init__(alerta_id)
        self.alerta_id = alerta_id


class EvaluationAlreadyRegistered(Exception):
    def __init__(self, alerta_id):
        super().__init__(alerta_id)
        self.alerta_id = alerta_id
