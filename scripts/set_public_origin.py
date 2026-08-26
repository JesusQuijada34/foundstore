from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'render.yaml'
text = path.read_text(encoding='utf-8')
needle = '    healthCheckPath: /healthz\n'
insert = needle + '    envVars:\n      - key: PUBLIC_ORIGIN\n        value: https://hifoundstore.onrender.com\n'
if '      - key: PUBLIC_ORIGIN\n' not in text:
    text = text.replace(needle + '    autoDeployTrigger: commit\n', '    autoDeployTrigger: commit\n' + insert, 1)
path.write_text(text, encoding='utf-8')
print(path)
