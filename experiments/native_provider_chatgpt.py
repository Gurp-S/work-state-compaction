"""Host-only first-party Codex gateway callback. Credentials never enter frames.

No login, credential refresh, redirects, retries or alternate providers. Catalog
access is not inference entitlement. Callers own allocation and receipt budgets.
"""
from base64 import urlsafe_b64decode
import json
from contextlib import nullcontext
from hashlib import sha256
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPRedirectHandler

BASE='https://chatgpt.com/backend-api/codex'


def media_type(status,original,body):
    if original in ('application/json','text/event-stream'):return original
    if original not in ('text/plain','application/octet-stream'):raise ValueError('provider_response_content_type')
    try:
        text=body.decode('utf-8',errors='strict')
        events=[json.loads(line[5:].strip()) for line in text.splitlines()
                if line.startswith('data:') and line[5:].strip() not in ('','[DONE]')]
        types=[v.get('type') for v in events if type(v) is dict]
        if events and len(types)==len(events) and 'response.created' in types and types[-1] in (
                'response.completed','response.failed','response.incomplete'):
            return 'text/event-stream'
    except (ValueError,UnicodeDecodeError):pass
    raise ValueError('provider_response_content_type')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl): return None


class ChatGPTProvider:
    def __init__(self, auth_file, *, timeout=45, opener=None,capture_directory=None):
        if type(timeout) is not int or not 1<=timeout<=90: raise ValueError('provider_timeout_invalid')
        self.auth_file=Path(auth_file);self.timeout=timeout
        self._open=opener or build_opener(NoRedirect()).open
        self.trace=[]
        self.capture=Path(capture_directory) if capture_directory is not None else None
        if self.capture:self.capture.mkdir(parents=True,exist_ok=False)

    def __repr__(self): return 'ChatGPTProvider(credentials=redacted)'

    def _headers(self):
        data=json.loads(self.auth_file.read_text(encoding='utf-8'))
        if data.get('auth_mode')!='chatgpt':raise ValueError('provider_auth_mode_unavailable')
        token=data.get('tokens',{}).get('access_token');account=data.get('tokens',{}).get('account_id')
        if type(token) is not str or not token or '\r' in token or '\n' in token:
            raise ValueError('provider_access_token_unavailable')
        try:
            payload=token.split('.')[1]
            claims=json.loads(urlsafe_b64decode(payload+'='*((-len(payload))%4)))
            expires=claims['exp']
        except (IndexError,ValueError,KeyError,TypeError):raise ValueError('provider_token_expiry_unavailable') from None
        if type(expires) not in (int,float) or expires<=time.time()+60:
            raise ValueError('provider_access_token_expired')
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
            'Accept':'text/event-stream','originator':'wsc_controlled_gateway',
            'User-Agent':'wsc-controlled-gateway/1'}
        if account is not None:
            if type(account) is not str or not account or '\r' in account or '\n' in account:
                raise ValueError('provider_account_header_invalid')
            headers['ChatGPT-Account-ID']=account
        return headers

    def _request(self,path,raw=None,*,limit):
        if path not in ('/responses','/models?client_version=0.165.0-alpha.1.2'):
            raise ValueError('provider_route_unregistered')
        headers=self._headers()
        if raw is None:headers['Accept']='application/json'
        request=Request(BASE+path,data=raw,headers=headers,method='GET' if raw is None else 'POST')
        start=time.perf_counter();entry=dict(method=request.method,path=path,request_bytes=len(raw) if raw is not None else 0)
        self.trace.append(entry)
        try:
            try:response=self._open(request,timeout=self.timeout)
            except HTTPError as error:response=error
            with response:
                status=response.code
                content_type=response.headers.get_content_type()
                entry.update(status=status,content_type=content_type,response_complete=False)
                blocks=[];total=0;deadline=time.monotonic()+self.timeout
                reader=getattr(response,'read1',response.read)
                capture=self.capture/f'{len(self.trace):03}-response.bin' if self.capture else None
                with capture.open('xb') if capture else nullcontext() as archive:
                    while True:
                        if time.monotonic()>deadline:raise TimeoutError('provider_response_deadline')
                        block=reader(min(65536,limit-total+1))
                        if not block:break
                        if archive:archive.write(block);archive.flush()
                        blocks.append(block);total+=len(block);entry['response_bytes']=total
                        if total>limit:raise ValueError('provider_response_size_exceeded')
                entry.update(response_bytes=total,response_complete=True)
                body=b''.join(blocks)
                entry['response_sha256']=sha256(body).hexdigest()
                if 300<=status<400:raise ValueError('provider_redirect_refused')
                effective=media_type(status,content_type,body);entry['effective_content_type']=effective
                return status,effective,body
        except BaseException as error:
            entry['error_type']=type(error).__name__;raise
        finally:entry['owner_network_wall_seconds']=time.perf_counter()-start

    def catalog(self):
        return self._request('/models?client_version=0.165.0-alpha.1.2',limit=2*1024*1024)

    def __call__(self,raw):
        if self.capture is None:raise ValueError('provider_raw_capture_required')
        if type(raw) is not bytes or not 0<len(raw)<=8*1024*1024:raise ValueError('provider_request_size')
        return self._request('/responses',raw,limit=16*1024*1024)
