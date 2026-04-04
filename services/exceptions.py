"""Typed HTTP client exceptions."""


class ServiceUnavailableError(Exception):
    def __init__(self, service: str, detail: str = ""):
        self.service = service
        self.detail = detail
        super().__init__(f"Service {service} unavailable: {detail}")


class NotFoundError(Exception):
    def __init__(self, entity: str, entity_id: str):
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} not found: {entity_id}")


class ValidationError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"Validation error: {detail}")
