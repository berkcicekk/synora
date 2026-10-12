import pytest
from builders import minimal_docx


@pytest.fixture
def valid_docx() -> bytes:
    return minimal_docx()
