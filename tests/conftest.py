"""I test non toccano mai il database vero: si usa un file temporaneo,
impostato PRIMA che app.db crei l'engine."""
import os
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(prefix="ndoma-test-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:TESTTOKEN")
