"""Exercise the pinned gateway in disposable local containers; never uses Kubernetes."""

import importlib.util
import json
import re
import ssl
import urllib.parse
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

repo = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('reconcile', repo / 'apps/ai/new-api/reconcile.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
suffix = secrets.token_hex(4)
network = 'new-api-smoke-' + suffix
database = network + '-postgres'
gateway = network + '-gateway'
mock = network + '-mock'
deployment = (repo / 'apps/ai/new-api/deployment.yaml').read_text()
image = re.search(r'^\s+image: (docker.io/calciumion/new-api:\S+)$', deployment, re.M)[1]
password = secrets.token_urlsafe(48)
db_password = secrets.token_urlsafe(32)

def docker(*args):
    result = subprocess.run(['docker', *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Docker command failed: ' + args[0] + '\n' + result.stderr[:2000])
    return result.stdout.strip()

def request(base, path, payload=None, token=None, method=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

mock_code = '''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
import os
models=json.loads(os.environ['MODEL_CATALOG'])
discovery_error=False
class Handler(BaseHTTPRequestHandler):
 def send(self,data):
  self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(data).encode())
 def do_GET(self):
  if self.path.startswith('/apis/kubeai.org/v1/namespaces/inference/models?'):
   if discovery_error:
    self.send_response(503); self.end_headers(); return
   self.send({'metadata':{},'items':[{'metadata':{'name':name},'spec':{'features':['TextGeneration']},'status':{'replicas':0}} for name in models]}); return
  code=self.headers.get('Authorization','').split()[-1]
  self.send({'sub':code,'preferred_username':code,'name':'Smoke User','email':code+'@example.test','email_verified':code!='unverified','groups':['/inference-users'] if code!='denied' else []})
 def do_POST(self):
  global models,discovery_error
  if self.path=='/test/catalog':
   models=json.loads(self.rfile.read(int(self.headers['Content-Length']))); self.send({}); return
  if self.path=='/test/discovery-error':
   discovery_error=json.loads(self.rfile.read(int(self.headers['Content-Length']))); self.send({}); return
  if self.path=='/token':
   body=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
   self.send({'access_token':body['code'][0],'token_type':'Bearer'}); return
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  assert self.path == '/v1/chat/completions', self.path
  if body.get('stream'):
   self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
   data={'id':'chatcmpl-smoke','object':'chat.completion.chunk','created':1,'model':body['model'],'choices':[{'index':0,'delta':{'role':'assistant','content':'gateway works'},'finish_reason':None}]}
   self.wfile.write(('data: '+json.dumps(data)+'\\n\\n').encode())
   data['choices']=[{'index':0,'delta':{},'finish_reason':'stop'}]
   data['usage']={'prompt_tokens':1,'completion_tokens':2,'total_tokens':3}
   self.wfile.write(('data: '+json.dumps(data)+'\\n\\ndata: [DONE]\\n\\n').encode()); return
  data={'id':'chatcmpl-smoke','object':'chat.completion','created':1,'model':body['model'],'choices':[{'index':0,'message':{'role':'assistant','content':'gateway works'},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':2,'total_tokens':3}}
  self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(data).encode())
HTTPServer(('0.0.0.0',8000),Handler).serve_forever()
'''

try:
    docker('network', 'create', network)
    with tempfile.TemporaryDirectory(prefix='new-api-smoke-') as folder:
        env_path = Path(folder) / 'database.env'
        env_path.write_text(f'POSTGRES_PASSWORD={db_password}\nPOSTGRES_USER=newapi\nPOSTGRES_DB=newapi\n')
        env_path.chmod(0o600)
        docker('run', '-d', '--name', database, '--network', network, '--env-file', str(env_path), 'postgres:17.6-alpine')
        for _ in range(60):
            status = subprocess.run(['docker', 'exec', database, 'pg_isready', '-U', 'newapi'], capture_output=True)
            if status.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('PostgreSQL not ready')
        catalog = sorted(re.search(r'^  name: (\S+)$', path.read_text(), re.M)[1] for path in (repo/'apps/ai/inference/models').glob('*.yaml') if "inference.orleans.io/expose: 'true'" in path.read_text())
        docker('run', '-d', '--name', mock, '--network', network, '-p', '127.0.0.1::8000', '-e', 'MODEL_CATALOG='+json.dumps(catalog), 'python:3.13.9-alpine3.22', 'python', '-c', mock_code)
        env_path = Path(folder) / 'gateway.env'
        env_path.write_text(f'SQL_DSN=postgresql://newapi:{db_password}@{database}:5432/newapi\nSESSION_SECRET={secrets.token_urlsafe(48)}\nMEMORY_CACHE_ENABLED=false\nCHANNEL_UPSTREAM_MODEL_UPDATE_TASK_ENABLED=false\n')
        env_path.chmod(0o600)
        docker('run', '-d', '--name', gateway, '--network', network, '--user', '65532:65532', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--tmpfs', '/data:rw,mode=1777', '--tmpfs', '/tmp:rw,mode=1777', '-p', '127.0.0.1::3000', '--env-file', str(env_path), image, '--log-dir', '/data/logs')
    port = json.loads(docker('inspect', gateway))[0]['NetworkSettings']['Ports']['3000/tcp'][0]['HostPort']
    base = f'http://127.0.0.1:{port}'
    for _ in range(60):
        try:
            request(base, '/api/setup')
            break
        except (OSError, ValueError):
            time.sleep(1)
    else:
        # Scrub any generated bearer strings before showing startup diagnostics.
        print(docker('logs', gateway)[-3000:])
        raise RuntimeError('New API not ready')
    print('PASS: non-root/read-only startup with PostgreSQL', flush=True)
    client = module.Client(base, password)
    config = json.loads((repo / 'apps/ai/new-api/gateway.json').read_text())
    config['upstream_base_url'] = 'http://' + mock + ':8000'
    secret = secrets.token_urlsafe(48)
    mock_port = json.loads(docker('inspect', mock))[0]['NetworkSettings']['Ports']['8000/tcp'][0]['HostPort']
    mock_base = 'http://127.0.0.1:'+mock_port
    with tempfile.TemporaryDirectory(prefix='new-api-discovery-') as folder:
        credentials = Path(folder)
        (credentials/'token').write_text('test-service-account')
        (credentials/'ca.crt').write_bytes(Path(ssl.get_default_verify_paths().cafile).read_bytes())
        discovery = module.ModelDiscovery(mock_base,credentials)
        module.reconcile_discovered(client, config, secret, discovery)
        module.reconcile_discovered(client, config, secret, discovery)
        original = list(client.channels())
        request(mock_base,'/test/discovery-error',True)
        try:
            module.reconcile_discovered(client, config, secret, discovery)
            raise AssertionError('Failed discovery was accepted')
        except module.DiscoveryError:
            pass
        assert list(client.channels()) == original
        request(mock_base,'/test/discovery-error',False)
        request(mock_base,'/test/catalog',[])
        module.reconcile_discovered(client, config, secret, discovery)
        assert list(client.channels())[0]['status']==2
        request(mock_base,'/test/catalog',catalog[:1])
        module.reconcile_discovered(client, config, secret, discovery)
        assert list(client.channels())[0]['models']==catalog[0]
        assert list(client.channels())[0]['status']==1
        request(mock_base,'/test/catalog',catalog)
        module.reconcile_discovered(client, config, secret, discovery)
        config['models']=discovery.models(config['model_discovery'])
    print('PASS: failed discovery preserves catalog; empty catalog disables; changed catalog re-enables and replaces models',flush=True)
    assert len(list(client.channels())) == 1
    providers = client.request('GET', '/api/custom-oauth-provider/')
    assert len(providers) == 1
    policy = json.loads(providers[0]['access_policy'])
    assert policy['conditions'][0]['value'] == '/inference-users'
    print('PASS: initialization, repeated reconciliation, OIDC group policy, model channel', flush=True)
    provider = module.provider_config(config, secret)
    provider['token_endpoint'] = 'http://' + mock + ':8000/token'
    provider['user_info_endpoint'] = 'http://' + mock + ':8000/userinfo'
    client.request('PUT',f"/api/custom-oauth-provider/{providers[0]['id']}",provider)
    for code in ['denied','unverified','allowed']:
        flow = request(base,'/api/oauth/state',{'provider':'sequoia','intent':'login'})['data']['flow_token']
        result = request(base,'/api/oauth/sequoia?' + urllib.parse.urlencode({'code':code,'state':flow}))
        assert result['success'] == (code=='allowed'), code
        if code=='allowed':
            login_data = result['data']
    print('PASS: OAuth signup admits verified group member and denies missing-group/unverified users',flush=True)
    user = module.Client(base, '')
    user.token = login_data['access_token']
    for name in ['app-one', 'app-two']:
        user.request('POST','/api/token/',{'name':name,'expired_time':-1,'unlimited_quota':True,'model_limits_enabled':True,'model_limits':config['models'][0],'group':'default'})
    tokens = user.request('GET','/api/token/?p=1&page_size=100')['items']
    assert len(tokens)==2
    key = user.request('POST',f"/api/token/{tokens[0]['id']}/key",{})['key']
    try:
        response=request(base,'/v1/chat/completions',{'model':config['models'][0],'messages':[{'role':'user','content':'hello'}]},key)
    except urllib.error.HTTPError as error:
        detail = json.load(error)
        print('Relay failure:', detail.get('error', {}).get('message', 'unknown').replace(key, '[key]'),flush=True)
        raise
    assert response['choices'][0]['message']['content']=='gateway works'
    stream_request = urllib.request.Request(base+'/v1/chat/completions',data=json.dumps({'model':config['models'][0],'messages':[{'role':'user','content':'hello'}],'stream':True}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
    with urllib.request.urlopen(stream_request,timeout=30) as response:
        stream=response.read().decode()
    assert 'gateway works' in stream and '[DONE]' in stream
    print('PASS: streaming preserves SSE content and completion marker',flush=True)
    print('PASS: non-admin user creates two independent keys; zero-quota local inference works',flush=True)
    try:
        request(base,'/v1/chat/completions',{'model':config['models'][1],'messages':[{'role':'user','content':'hello'}]},key)
        raise AssertionError('Model restriction did not reject request')
    except urllib.error.HTTPError as error:
        assert error.code in (403, 401), error.code
    user.request('DELETE',f"/api/token/{tokens[0]['id']}")
    try:
        request(base,'/v1/models',token=key)
        raise AssertionError('Revoked key still accepted')
    except urllib.error.HTTPError as error:
        assert error.code==401, error.code
    print('PASS: per-key model restrictions and revoked-key rejection',flush=True)
    second_key = user.request('POST',f"/api/token/{tokens[1]['id']}/key",{})['key']
    limited = False
    for _ in range(21):
        try:
            request(base,'/v1/chat/completions',{'model':config['models'][0],'messages':[{'role':'user','content':'hello'}]},second_key)
        except urllib.error.HTTPError as error:
            assert error.code==429, error.code
            limited=True
            break
    assert limited, 'Per-user rate limit did not reject excess requests'
    print('PASS: per-user inference rate limit rejects excess requests',flush=True)
finally:
    for name in [gateway,mock,database]:
        subprocess.run(['docker','rm','-f','-v',name],capture_output=True)
    subprocess.run(['docker','network','rm',network],capture_output=True)
