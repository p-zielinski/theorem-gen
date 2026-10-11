"""Errors for the theorem generator."""


class TheoremGenError(Exception):
    """Base error for generation, export, and expressions."""


class ExprError(TheoremGenError):
    """A Nat expression cannot be built from the given value."""


class TypingError(ExprError):
    """An operation is not allowed for the given types."""


class TheoremError(TheoremGenError):
    """A theorem or its metadata is not well formed."""


class ExportError(TheoremGenError):
    """The theorem cannot be written as the supported Lean subset."""


class GenerationError(TheoremGenError):
    """The generator stopped because of its configuration, not because Lean rejected a proof."""


class RegistryError(TheoremGenError):
    """A registry update is missing a dependency or would create a cycle."""


class DefinitionError(TheoremGenError):
    """A definition is outside the supported fragment."""
