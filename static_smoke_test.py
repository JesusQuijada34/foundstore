import ast
from pathlib import Path

source = Path("app.py").read_text(encoding="utf-8")
config = Path("config.py").read_text(encoding="utf-8")
ast.parse(source)
ast.parse(config)
assert "generate_password_hash" in source
assert "check_password_hash" in source
assert "_verify_telegram_init_data" in source
assert "hmac.compare_digest" in source
assert "if telegram_user and github.authorized" in source
assert "SECRET_KEY debe configurarse en producción" in config
assert "<platform>AlphaCube</platform>" in Path("details.xml").read_text(encoding="utf-8")
print("FOUNDSTORE_SECURITY_STATIC_CHECK_OK")
