from collections.abc import Generator
from contextlib import contextmanager

import journalist_app
from sdconfig import SecureDropConfig


@contextmanager
def app_context() -> Generator:
    config = SecureDropConfig.get_current()
    with journalist_app.create_app(config).app_context():
        yield
