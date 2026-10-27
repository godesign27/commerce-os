"""The result type every policy rule returns."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Violation:
    code: str        # stable machine-readable reason, e.g. "duplicate_option_values"
    path: str        # where in the document, e.g. "products[0].variants[1]"
    message: str     # what a reviewer reads

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message

    def as_dict(self) -> dict:
        return asdict(self)
