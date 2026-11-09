"""Direct DeepSeek chat-completions provider.

The app historically called the Codex CLI, which needs a ChatGPT quota and no
longer supports chat-style custom providers. DeepSeek exposes an OpenAI
compatible endpoint, so model calls go straight there and Codex stays as a
fallback for machines without a key.
"""
import json
import os
import re
import urllib.request

BASE = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/chat/completions')


def key():
    value = os.environ.get('DEEPSEEK_API_KEY', '').strip()
    if value:
        return value
    for candidate in ('~/.zshrc', '~/.zprofile', '~/.profile', '~/.bash_profile'):
        path = os.path.expanduser(candidate)
        try:
            with open(path, encoding='utf-8', errors='ignore') as handle:
                for line in handle:
                    match = re.search(r'DEEPSEEK_API_KEY\s*=\s*"?([^"\s]+)"?', line)
                    if match and match.group(1).startswith('sk-'):
                        return match.group(1)
        except OSError:
            continue
    return ''


def available():
    return bool(key())


def chat(messages, model=None, timeout=600, json_mode=False, temperature=0.3):
    """One blocking completion; raises on transport or protocol errors."""
    if not isinstance(messages, list) or not messages:
        raise ValueError('messages 必须是非空数组')
    payload = {'model': model or os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat'),
               'messages': messages, 'temperature': temperature, 'stream': False}
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    request = urllib.request.Request(BASE, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                     headers={'Authorization': 'Bearer ' + key(),
                                              'Content-Type': 'application/json'})
    # Domestic endpoint: bypass the system proxy that the VPN installs.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = json.load(response)
    choices = body.get('choices') or []
    if not choices:
        raise RuntimeError('model_empty_response')
    content = (choices[0].get('message') or {}).get('content') or ''
    if not content.strip():
        raise RuntimeError('model_empty_content')
    return content.strip()
