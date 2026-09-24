"""Resolve one explicitly named member session through its normal logged-in API.

Run with the existing local Playwright environment. Credentials and signed URLs
are written only to the requested private transport file, never stdout.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit, urlunsplit


def public_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, '', ''))


def resolve(slug, auth_state, browser_root, output, inspect_only=False, file_index=None):
    from playwright.sync_api import sync_playwright
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', slug):
        raise ValueError('Invalid session slug')
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(browser_root)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=pw.chromium.executable_path)
        context = browser.new_context(storage_state=str(auth_state))
        page = context.new_page()
        nonce = []
        details = []

        def request_seen(request):
            if urlsplit(request.url).hostname == 'members.urm.academy':
                value = request.headers.get('x-wp-nonce')
                if value:
                    nonce[:] = [value]

        def response_seen(response):
            if '/wp-json/wp/v2/ntm_session' in response.url and response.status == 200:
                try:
                    value = response.json()
                    for item in value if isinstance(value, list) else [value]:
                        if item.get('slug') == slug:
                            details[:] = [item]
                except Exception:
                    pass

        page.on('request', request_seen)
        page.on('response', response_seen)
        source_page = f'https://members.urm.academy/ntm-sessions/{slug}/'
        page.goto(source_page, wait_until='domcontentloaded', timeout=45000)
        deadline = time.monotonic()+25
        while not details and time.monotonic() < deadline:
            page.wait_for_timeout(250)
        headers = {'X-WP-Nonce': nonce[0]} if nonce else {}
        if not details:
            response = context.request.get(f'https://members.urm.academy/wp-json/wp/v2/ntm_session?slug={slug}', headers=headers)
            if response.status != 200:
                raise RuntimeError('Session metadata unavailable; login or upstream review required')
            details = [v for v in response.json() if v.get('slug') == slug]
        if len(details) != 1 or details[0].get('hasAccess') is not True:
            raise RuntimeError('Session access unavailable; manual login required')
        item = details[0]
        master = item.get('songFile')
        if not isinstance(master, str) or urlsplit(master).scheme != 'https':
            raise RuntimeError('No unambiguous supplied finished-audio asset')
        files = item.get('sessionFiles') or {}
        if files.get('rateLimited'):
            raise RuntimeError('Provider download limit active; stop without retrying')
        download_items = [v for v in files.get('files', []) if v.get('type') == 'download' and isinstance(v.get('fileIndex'), int)]
        if not download_items:
            raise RuntimeError('No normal session archive download is available')
        if file_index is None:
            labels={re.sub(r'\s*\((?:Europe|Asia|US|USA|North America)\)\s*$', '', v.get('title',''), flags=re.I).strip().casefold() for v in download_items}
            if len(labels)>1:
                raise RuntimeError('Multiple differently named archives require an explicit file index')
            selection = min(download_items, key=lambda v: v['fileIndex'])
        else:
            matches=[v for v in download_items if v['fileIndex']==file_index]
            if len(matches)!=1:raise RuntimeError('Selected archive index unavailable')
            selection=matches[0]
        safe = {'session_id': item['id'], 'slug': slug, 'title': item.get('bandSong') or slug,
                'source_page': source_page, 'has_access': True,
                'master_source': public_url(master), 'selected_file_index': selection['fileIndex'],
                'session_info': item.get('sessionInfo', []),
                'licensed_local_use_only': True, 'automatic_reference_qualification': False}
        transport = {'metadata': safe, 'master_url': master}
        if not inspect_only:
            response = context.request.post(
                f"https://members.urm.academy/wp-json/urm/v1/sessions/{item['id']}/download-link",
                headers=headers, data={'fileIndex': selection['fileIndex']}, timeout=45000)
            if response.status != 200:
                raise RuntimeError(f'Provider archive request HTTP {response.status}; stop without retrying')
            body = response.json()
            link = body.get('link')
            if not isinstance(link, str) or urlsplit(link).scheme != 'https':
                raise RuntimeError('Provider did not supply an authorized archive link')
            transport['archive_url'] = link
            safe['rate_limit_response'] = body.get('rateLimit')
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(transport, f, ensure_ascii=False, indent=2)
        context.close()
        browser.close()
        return {'session_id': item['id'], 'has_access': True, 'master_found': True,
                'archive_link_requested': not inspect_only}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['slug', 'auth-state', 'browser-root', 'output']:
        p.add_argument('--'+name, required=True)
    p.add_argument('--inspect-only', action='store_true')
    p.add_argument('--file-index', type=int)
    args = p.parse_args()
    try:
        print(json.dumps(resolve(args.slug, args.auth_state, args.browser_root, args.output, args.inspect_only, args.file_index)))
    except Exception as error:
        # Browser exceptions can contain bearer URLs, headers or account data.
        print(json.dumps({'status': 'member_access_needs_attention', 'error_type': type(error).__name__}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
